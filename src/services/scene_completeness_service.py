from __future__ import annotations

from pathlib import Path

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
)
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessReport,
    SceneCompletenessStatus,
)
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)

_IN_PROGRESS_STATES = frozenset(
    {
        GoogleFlowGenerationState.PLANNED,
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.ANALYZING,
        GoogleFlowGenerationState.CONFIRMATION_REQUIRED,
        GoogleFlowGenerationState.CONFIRMING,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
    }
)

_NEEDS_ATTENTION_STATES = frozenset(
    {
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
        GoogleFlowGenerationState.QC_FAILED,
        GoogleFlowGenerationState.AUTH_REQUIRED,
        GoogleFlowGenerationState.HUMAN_ACTION_REQUIRED,
        GoogleFlowGenerationState.UI_CHANGED,
        GoogleFlowGenerationState.FAILED,
    }
)


class SceneCompletenessService:
    """
    Real, deterministic, code-only per-scene readiness check: is this
    scene actually generated, downloaded, and attached - never an LLM
    judgment call, and never trusting a provider's own self-reported
    status (Google Flow's "downloaded" toast has been directly proven
    to lie - only 1 of 4 files it reported as downloaded had actually
    landed on disk, this session).

    A scene resolved through a non-Flow source (manual upload, stock)
    is judged purely on whether it is actually attached in
    job.video_clips with a real file - the Flow ledger simply does not
    apply to it, and it is not penalized for having no attempt there.
    """

    def check(self, job: VideoJob) -> SceneCompletenessReport:
        clips_by_scene = {clip.scene_number: clip for clip in job.video_clips}

        entries = [
            self._check_scene(
                scene_number=scene.scene_number,
                clip=clips_by_scene.get(scene.scene_number),
                attempt=GoogleFlowGenerationLedgerService.latest_attempt_for_scene(
                    job, scene.scene_number
                ),
            )
            for scene in sorted(job.scenes, key=lambda scene: scene.scene_number)
        ]

        return SceneCompletenessReport(entries=entries)

    @classmethod
    def _check_scene(
        cls,
        *,
        scene_number: int,
        clip: VideoClip | None,
        attempt: GoogleFlowGenerationAttempt | None,
    ) -> SceneCompletenessEntry:
        attached = clip is not None and bool(clip.local_file)

        if attached:
            assert clip is not None

            return SceneCompletenessEntry(
                scene_number=scene_number,
                status=SceneCompletenessStatus.READY,
                generated=True,
                downloaded=True,
                attached=True,
                detail=f"Attached from {clip.source_type.value}: {clip.local_file}.",
            )

        if attempt is None:
            return SceneCompletenessEntry(
                scene_number=scene_number,
                status=SceneCompletenessStatus.NOT_STARTED,
                generated=False,
                downloaded=False,
                attached=False,
                detail="No Google Flow attempt has been submitted for this scene.",
            )

        generated = attempt.state in (
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
            GoogleFlowGenerationState.DOWNLOADED,
            GoogleFlowGenerationState.QC_FAILED,
            GoogleFlowGenerationState.READY,
        )
        downloaded = cls._file_is_really_on_disk(attempt.downloaded_file)

        if attempt.state in _NEEDS_ATTENTION_STATES:
            return SceneCompletenessEntry(
                scene_number=scene_number,
                status=SceneCompletenessStatus.NEEDS_ATTENTION,
                generated=generated,
                downloaded=downloaded,
                attached=attached,
                detail=(
                    f"Attempt is at {attempt.state.value} - requires operator "
                    "attention before this scene can be attached."
                ),
            )

        if attempt.state in _IN_PROGRESS_STATES:
            return SceneCompletenessEntry(
                scene_number=scene_number,
                status=SceneCompletenessStatus.IN_PROGRESS,
                generated=generated,
                downloaded=downloaded,
                attached=attached,
                detail=f"Attempt is at {attempt.state.value}.",
            )

        # GoogleFlowGenerationState.READY but never actually attached -
        # a real gap (the third failure point this session found: a
        # file can exist without the job ever having attached it).
        return SceneCompletenessEntry(
            scene_number=scene_number,
            status=SceneCompletenessStatus.NEEDS_ATTENTION,
            generated=generated,
            downloaded=downloaded,
            attached=False,
            detail=(
                "Attempt reached READY but was never attached to "
                "job.video_clips - apply the AI_GENERATE decision for "
                "this scene."
            ),
        )

    @staticmethod
    def _file_is_really_on_disk(file_path: str | None) -> bool:
        if not file_path:
            return False

        try:
            path = Path(file_path)

            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False
