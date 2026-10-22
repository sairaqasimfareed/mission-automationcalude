from __future__ import annotations

import re
from pathlib import Path

from src.models.asset_state import (
    AssetCandidate,
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.bulk_clip_ingestion import (
    BulkClipIngestionEntry,
    BulkClipIngestionEntryStatus,
    BulkClipIngestionResult,
)
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.invalidation_service import InvalidationService
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService

_SUPPORTED_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
)
_LEADING_NUMBER_PATTERN = re.compile(r"^(\d+)")


class BulkClipIngestionService:
    """
    Matches a folder of manually-downloaded clip files back to the
    scenes they belong to (by the leading scene number in each
    filename, per ScenePromptExportService's suggested naming) and
    assigns each one through the real manual-upload workflow -
    SceneAssetWorkflowService.apply_decision(), the exact same call
    the Render Workspace GUI makes for one file at a time. This is
    only a batching layer over that existing, validated path: it does
    not reimplement upload validation, storage, or clip-building.
    """

    def __init__(
        self,
        *,
        asset_workflow_service: SceneAssetWorkflowService,
        video_clip_builder_service: SceneAssetVideoClipBuilderService | None = None,
        invalidation_service: InvalidationService | None = None,
    ) -> None:
        self.asset_workflow_service = asset_workflow_service
        self.video_clip_builder_service = (
            video_clip_builder_service or SceneAssetVideoClipBuilderService()
        )
        self.invalidation_service = invalidation_service or InvalidationService()

    def remove_scene_clip(self, *, job: VideoJob, scene_number: int) -> None:
        """
        Detach whatever clip/asset-state a scene currently has,
        resetting it to never-started - the undo counterpart to
        ingest_one(), for when a manual upload or a completed AI
        generation needs to be cleared so something else can be
        attached instead.

        Deliberately never touches the Google Flow ledger
        (job.flow_generation_attempts): a terminal (READY/QC_FAILED/
        FAILED) attempt there is never itself an obstacle to
        GoogleFlowGenerationLedgerService.create_attempt() starting a
        fresh one - its own in-flight guard only ever blocks a
        NON-terminal attempt.

        Real-world finding, 2026-09-28: this method's own removal of
        the scene's SceneAssetState (just below) IS load-bearing for a
        later Generate click, though - a READY attempt left behind
        here is exactly what SceneVideoGenerationService._drive_to_
        terminal() now checks for (an "orphaned READY": still READY,
        but the scene has no SceneAssetState referencing it any more)
        to tell "already attached, nothing to do" apart from "was
        attached, now removed, needs a fresh Flow call." Clearing
        scene_asset_states here is what makes that check fire.
        """

        job.scene_asset_states = [
            state
            for state in job.scene_asset_states
            if state.scene_number != scene_number
        ]
        job.video_clips = self.video_clip_builder_service.build_clips(
            scenes=job.scenes, states=job.scene_asset_states
        )
        self.invalidation_service.clear_stale(job, "scene_asset_states")
        self.invalidation_service.clear_stale(job, "video_clips")
        self.invalidation_service.on_scene_replaced(
            job,
            scene_number=scene_number,
            reason=f"Scene {scene_number}'s asset was removed.",
        )

    def ingest(
        self, *, job: VideoJob, source_directory: Path
    ) -> BulkClipIngestionResult:
        if not source_directory.is_dir():
            raise ValueError(f"'{source_directory}' is not a directory.")

        scenes_by_number = {scene.scene_number: scene for scene in job.scenes}
        states_by_number = {
            state.scene_number: state for state in job.scene_asset_states
        }

        candidate_files = sorted(
            path
            for path in source_directory.iterdir()
            if path.is_file() and path.suffix.lower() in _SUPPORTED_VIDEO_EXTENSIONS
        )

        entries: list[BulkClipIngestionEntry] = []

        for file_path in candidate_files:
            entries.append(
                self._ingest_one(
                    file_path=file_path,
                    job=job,
                    scenes_by_number=scenes_by_number,
                    states_by_number=states_by_number,
                )
            )

        job.scene_asset_states = list(states_by_number.values())
        job.video_clips = self.video_clip_builder_service.build_clips(
            scenes=job.scenes, states=job.scene_asset_states
        )
        self.invalidation_service.clear_stale(job, "scene_asset_states")
        self.invalidation_service.clear_stale(job, "video_clips")

        for entry in entries:
            if (
                entry.status == BulkClipIngestionEntryStatus.ASSIGNED
                and entry.scene_number is not None
            ):
                self.invalidation_service.on_scene_replaced(
                    job, scene_number=entry.scene_number
                )

        ready_scene_numbers = {
            state.scene_number for state in job.scene_asset_states if state.is_ready
        }
        scenes_still_missing = sorted(
            scene_number
            for scene_number in scenes_by_number
            if scene_number not in ready_scene_numbers
        )

        return BulkClipIngestionResult(
            entries=entries, scenes_still_missing_a_file=scenes_still_missing
        )

    def ingest_one(
        self, *, job: VideoJob, scene_number: int, file_path: Path
    ) -> BulkClipIngestionEntry:
        """
        Attach a single file to a single, explicitly-known scene - the
        same validated manual-upload path ingest() uses per file,
        without a whole folder scan or filename-based scene matching.
        The natural companion to ingest()'s bulk workflow for
        attaching just one scene's clip at a time (e.g. the Clip
        Workspace's per-scene "Upload..." button, right next to that
        scene's own Generate button) - the scene is already known from
        which button was clicked, so this never needs to parse it back
        out of the filename the way the bulk folder scan does.
        """

        scenes_by_number = {scene.scene_number: scene for scene in job.scenes}
        states_by_number = {
            state.scene_number: state for state in job.scene_asset_states
        }

        scene = scenes_by_number.get(scene_number)

        if scene is None:
            entry = BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.NO_MATCHING_SCENE,
                detail=f"No scene {scene_number} in this project.",
            )
        else:
            entry = self._apply_upload(
                file_path=file_path,
                job=job,
                scene=scene,
                states_by_number=states_by_number,
            )

        job.scene_asset_states = list(states_by_number.values())
        job.video_clips = self.video_clip_builder_service.build_clips(
            scenes=job.scenes, states=job.scene_asset_states
        )
        self.invalidation_service.clear_stale(job, "scene_asset_states")
        self.invalidation_service.clear_stale(job, "video_clips")

        if entry.status == BulkClipIngestionEntryStatus.ASSIGNED:
            self.invalidation_service.on_scene_replaced(job, scene_number=scene_number)

        return entry

    def ingest_part(
        self,
        *,
        job: VideoJob,
        scene_number: int,
        part_index: int,
        part_count: int,
        file_path: Path,
    ) -> BulkClipIngestionEntry:
        """
        Attach one file to ONE PART of a scene that is made of several clips (0 = Part 1).
        The same validation as ingest_one(); the file is kept against that part only. The
        scene counts as having a clip once every part is there - until then the uploaded
        parts wait on the scene's state, and a part already attached (from a generation or an
        earlier upload) is replaced in place, the other parts untouched.
        """

        scene = next((s for s in job.scenes if s.scene_number == scene_number), None)

        if scene is None:
            return BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.NO_MATCHING_SCENE,
                detail=f"No scene {scene_number} in this project.",
            )

        if scene.source_locked:
            return BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.FAILED_VALIDATION,
                detail=f"Scene {scene_number} is locked - unlock it before reassigning.",
            )

        if not 0 <= part_index < part_count:
            raise ValueError(f"Part {part_index + 1} is not one of {part_count} parts.")

        existing = next(
            (s for s in job.scene_asset_states if s.scene_number == scene_number), None
        )
        scratch = (
            existing.model_copy(deep=True)
            if existing is not None
            else self.asset_workflow_service.start(scene)
        )
        checked = self.asset_workflow_service.apply_decision(
            scene=scene,
            state=scratch,
            decision=AssetUserDecision.MANUAL_UPLOAD,
            manual_upload_path=str(file_path),
            project_id=job.project_name,
        )

        if not checked.is_ready or checked.selected_candidate is None:
            return BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.FAILED_VALIDATION,
                detail=(
                    checked.active_failure.message
                    if checked.active_failure is not None
                    else "Manual upload could not be validated."
                ),
            )

        state = existing or self.asset_workflow_service.start(scene)
        parts: dict[int, AssetCandidate] = dict(state.pending_part_uploads)

        if state.is_ready and state.selected_candidate is not None:
            parts[0] = state.selected_candidate

            for offset, candidate in enumerate(
                state.additional_ai_generated_sub_clips, start=1
            ):
                parts[offset] = candidate

        parts[part_index] = checked.selected_candidate

        if all(index in parts for index in range(part_count)):
            state.pending_part_uploads = {}
            state.selected_candidate = parts[0]
            state.additional_ai_generated_sub_clips = [
                parts[index] for index in range(1, part_count)
            ]
            state.selected_source = parts[0].source_type
            state.manual_upload_path = (
                parts[0].file_path
                if parts[0].source_type == SceneSourceType.MANUAL_UPLOAD
                else state.manual_upload_path
            )
            state.user_decision = AssetUserDecision.MANUAL_UPLOAD
            state.clear_active_failure()
            state.status = AssetWorkflowStatus.READY
            detail = f"Assigned to scene {scene_number}: all {part_count} parts are in."
        else:
            state.pending_part_uploads = parts
            missing = [
                str(index + 1) for index in range(part_count) if index not in parts
            ]
            detail = (
                f"Part {part_index + 1} saved for scene {scene_number} - "
                f"upload part {', '.join(missing)} to finish it."
            )

        if existing is None:
            job.scene_asset_states.append(state)

        job.video_clips = self.video_clip_builder_service.build_clips(
            scenes=job.scenes, states=job.scene_asset_states
        )
        self.invalidation_service.clear_stale(job, "scene_asset_states")
        self.invalidation_service.clear_stale(job, "video_clips")
        self.invalidation_service.on_scene_replaced(job, scene_number=scene_number)

        return BulkClipIngestionEntry(
            file_name=file_path.name,
            scene_number=scene_number,
            status=BulkClipIngestionEntryStatus.ASSIGNED,
            detail=detail,
        )

    def _ingest_one(
        self,
        *,
        file_path: Path,
        job: VideoJob,
        scenes_by_number: dict[int, Scene],
        states_by_number: dict[int, SceneAssetState],
    ) -> BulkClipIngestionEntry:
        scene_number = self._parse_scene_number(file_path.name)
        scene = scenes_by_number.get(scene_number) if scene_number is not None else None

        if scene is None:
            detail = (
                "Filename does not start with a scene number."
                if scene_number is None
                else f"No scene {scene_number} in this project."
            )

            return BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.NO_MATCHING_SCENE,
                detail=detail,
            )

        return self._apply_upload(
            file_path=file_path,
            job=job,
            scene=scene,
            states_by_number=states_by_number,
        )

    def _apply_upload(
        self,
        *,
        file_path: Path,
        job: VideoJob,
        scene: Scene,
        states_by_number: dict[int, SceneAssetState],
    ) -> BulkClipIngestionEntry:
        scene_number = scene.scene_number

        if scene.source_locked:
            return BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.FAILED_VALIDATION,
                detail=f"Scene {scene_number} is locked - unlock it before reassigning.",
            )

        state = states_by_number.get(scene_number) or self.asset_workflow_service.start(
            scene
        )

        updated_state = self.asset_workflow_service.apply_decision(
            scene=scene,
            state=state,
            decision=AssetUserDecision.MANUAL_UPLOAD,
            manual_upload_path=str(file_path),
            project_id=job.project_name,
        )
        states_by_number[scene_number] = updated_state

        if not updated_state.is_ready:
            failure_message = (
                updated_state.active_failure.message
                if updated_state.active_failure is not None
                else "Manual upload could not be validated."
            )

            return BulkClipIngestionEntry(
                file_name=file_path.name,
                scene_number=scene_number,
                status=BulkClipIngestionEntryStatus.FAILED_VALIDATION,
                detail=failure_message,
            )

        return BulkClipIngestionEntry(
            file_name=file_path.name,
            scene_number=scene_number,
            status=BulkClipIngestionEntryStatus.ASSIGNED,
            detail=f"Assigned to scene {scene_number}.",
        )

    @staticmethod
    def _parse_scene_number(filename: str) -> int | None:
        match = _LEADING_NUMBER_PATTERN.match(filename)

        if not match:
            return None

        return int(match.group(1))
