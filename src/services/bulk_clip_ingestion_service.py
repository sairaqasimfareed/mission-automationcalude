from __future__ import annotations

import re
from pathlib import Path

from src.models.asset_state import AssetUserDecision, SceneAssetState
from src.models.bulk_clip_ingestion import (
    BulkClipIngestionEntry,
    BulkClipIngestionEntryStatus,
    BulkClipIngestionResult,
)
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

        # scene is matched, so its own scene_number (always int) is the
        # authoritative key from here on - narrows away the Optional.
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
