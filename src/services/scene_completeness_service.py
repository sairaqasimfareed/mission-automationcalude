from __future__ import annotations

from pathlib import Path

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
)
from src.models.muse_generation import MuseGenerationAttempt
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
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService

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
                attempt=self._latest_attempt_for_scene(job, scene.scene_number),
            )
            for scene in sorted(job.scenes, key=lambda scene: scene.scene_number)
        ]

        return SceneCompletenessReport(entries=entries)

    def sub_clip_statuses(
        self, job: VideoJob, scene_number: int
    ) -> list[tuple[int, str]]:
        """
        Real-world finding, 2026-09-29 (multi-clip scene splitting): a
        split scene's own aggregate check() entry reports only its
        MOST RECENT sub-clip's state, giving an operator no visibility
        into which of N sub-clips is actually stuck - the Clip
        Workspace's own per-scene row shows this breakdown underneath
        the aggregate status, mirroring the Prompts tab's own
        "Part X of Y" breakdown for the same feature (both read the
        same real ledger data; neither predicts a split plan ahead of
        actual attempts existing).

        Returns [] for a scene with at most one distinct
        clip_sequence_index across both ledgers - not split, or not
        started yet - so an ordinary scene's row is completely
        unaffected by this method existing.
        """

        flow_indices = {
            attempt.request.clip_sequence_index
            for attempt in job.flow_generation_attempts
            if attempt.request.scene_number == scene_number
        }
        muse_indices = {
            attempt.request.clip_sequence_index
            for attempt in job.muse_generation_attempts
            if attempt.request.scene_number == scene_number
        }
        indices = sorted(flow_indices | muse_indices)

        if len(indices) <= 1:
            return []

        return [
            (
                index,
                self._sub_clip_status_label(
                    self._latest_attempt_for_scene(
                        job, scene_number, clip_sequence_index=index
                    )
                ),
            )
            for index in indices
        ]

    @staticmethod
    def _sub_clip_status_label(
        attempt: GoogleFlowGenerationAttempt | MuseGenerationAttempt | None,
    ) -> str:
        if attempt is None:
            return "not started"

        state_value: str = attempt.state.value

        if attempt.state in _NEEDS_ATTENTION_STATES:
            return f"needs_attention - {state_value}"

        return state_value

    @staticmethod
    def _latest_attempt_for_scene(
        job: VideoJob, scene_number: int, *, clip_sequence_index: int = 0
    ) -> GoogleFlowGenerationAttempt | MuseGenerationAttempt | None:
        """
        The most recently created attempt for one (scene_number,
        clip_sequence_index) sub-clip, across BOTH provider ledgers.

        Real-world finding, 2026-09-29: this used to check only
        job.flow_generation_attempts - entirely blind to
        job.muse_generation_attempts once a second provider existed. A
        scene abandoned on one provider and then generated through the
        other (Scene.preferred_profile_id changed after the fact) left
        an old, terminal attempt on the FIRST provider's ledger that
        this method reported exclusively - "Attempt is at failed" for
        a scene whose real, current attempt had just started fresh on
        the other provider. Both GoogleFlowGenerationState and
        MuseGenerationState are (str, Enum) with matching values for
        every state Muse actually has, so _check_scene's existing
        frozenset-membership checks below work correctly regardless of
        which provider the returned attempt came from - no further
        changes needed there.

        clip_sequence_index (default 0, matching every pre-Phase-5
        scene's only sub-clip) exists so sub_clip_statuses() above can
        resolve one specific sub-clip's own latest attempt rather than
        always the scene's single most recent one across every index.
        """

        flow_attempt = GoogleFlowGenerationLedgerService.latest_attempt_for_scene(
            job, scene_number, clip_sequence_index=clip_sequence_index
        )
        muse_attempt = MuseGenerationLedgerService.latest_attempt_for_scene(
            job, scene_number, clip_sequence_index=clip_sequence_index
        )

        candidates = [
            attempt for attempt in (flow_attempt, muse_attempt) if attempt is not None
        ]

        if not candidates:
            return None

        return max(candidates, key=lambda attempt: attempt.created_at)

    @classmethod
    def _check_scene(
        cls,
        *,
        scene_number: int,
        clip: VideoClip | None,
        attempt: GoogleFlowGenerationAttempt | MuseGenerationAttempt | None,
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
                detail="No generation attempt has been submitted for this scene.",
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
