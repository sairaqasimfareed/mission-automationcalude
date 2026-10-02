from __future__ import annotations

from src.models.asset_state import AssetWorkflowStatus
from src.models.final_export import FinalExportPackage
from src.models.render_result import RenderStatus
from src.models.scene import Scene
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.models.video_job import VideoJob
from src.services.content_studio_journey_service import (
    ContentStudioJourneyService,
    JourneyCheckpoint,
    JourneyCheckpointStatus,
)

_FAILED_ASSET_STATUSES = frozenset(
    {
        AssetWorkflowStatus.FAILED_RECOVERABLE,
        AssetWorkflowStatus.FAILED_FATAL,
        AssetWorkflowStatus.FAILED,
    }
)


class ProjectProductionJourneyService:
    """
    The full, end-to-end production journey for one VideoJob - content
    generation (via ContentStudioJourneyService's own 8 checkpoints,
    reused rather than re-derived) through scene planning, assets,
    audio, timeline, render, and packaging.

    Real-world finding, 2026-09-30: ProjectHeaderService's own
    "current stage" field only ever read VideoJob.current_stage, which
    only the legacy ContentPipeline keeps updated -
    ContentIntelligencePipeline's real projects showed a permanently
    stale stage (e.g. "research" while a project was actually
    generating clips) - confirmed live by the user. This service is
    the pipeline-agnostic replacement: every checkpoint here is
    recomputed fresh from the job's own real, persisted artifacts,
    the same "never trust a stale verdict" convention
    ProductionReadinessService/ContentStudioJourneyService already
    establish - nothing here is cached, and nothing here is a
    duplicate blocker/readiness model (see ProductionReadinessService
    for that - this answers "how far did we get," not "what's
    blocking").

    seo_package/thumbnail/final_export are optional because - unlike
    every other artifact this service reads - they live in JobStore,
    not on VideoJob itself (see JobStore.get_seo_package/get_thumbnail/
    get_final_export). A caller without a job_store reference (a
    service-layer test, for instance) can simply omit them and get an
    honest "not started" for those three checkpoints.
    """

    def __init__(
        self,
        *,
        content_journey_service: ContentStudioJourneyService | None = None,
    ) -> None:
        self.content_journey_service = (
            content_journey_service or ContentStudioJourneyService()
        )

    def compute(
        self,
        job: VideoJob,
        *,
        seo_package: SEOPackage | None = None,
        thumbnail: ThumbnailArtifact | None = None,
        final_export: FinalExportPackage | None = None,
    ) -> list[JourneyCheckpoint]:
        return [
            *self.content_journey_service.compute(job),
            self._scene_planning_checkpoint(job),
            self._asset_checkpoint(job),
            self._audio_checkpoint(job),
            self._timeline_checkpoint(job),
            self._render_checkpoint(job),
            self._seo_checkpoint(seo_package),
            self._thumbnail_checkpoint(thumbnail),
            self._final_export_checkpoint(final_export),
        ]

    def current_stage_label(
        self,
        job: VideoJob,
        checkpoints: list[JourneyCheckpoint],
    ) -> str:
        """
        Return a human-facing "what stage is this project at" label.

        A project that has never touched ContentIntelligencePipeline
        (none of its own marker fields are set - audience_promise,
        selected_story_angle, story_blueprint, selected_hook,
        generated_script; job.script is the legacy pipeline's own,
        distinct field, confirmed by grep that ContentPipeline never
        assigns any of the CI-only fields above) falls back to
        VideoJob.current_stage exactly as before - that field IS
        accurate for a legacy-pipeline project, so this only replaces
        it where it was actually wrong.
        """

        uses_content_intelligence = (
            job.audience_promise is not None
            or job.selected_story_angle is not None
            or job.story_blueprint is not None
            or job.selected_hook is not None
            or job.generated_script is not None
        )

        if not uses_content_intelligence:
            return job.current_stage.value.replace("_", " ")

        for checkpoint in checkpoints:
            if checkpoint.status != JourneyCheckpointStatus.APPROVED:
                return checkpoint.label

        return "Completed"

    @staticmethod
    def _scene_planning_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        if not job.scenes:
            return JourneyCheckpoint(
                label="Scene Planning", status=JourneyCheckpointStatus.NOT_STARTED
            )

        return JourneyCheckpoint(
            label="Scene Planning", status=JourneyCheckpointStatus.APPROVED
        )

    @staticmethod
    def _asset_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        if not job.scenes or not job.scene_asset_states:
            return JourneyCheckpoint(
                label="Assets", status=JourneyCheckpointStatus.NOT_STARTED
            )

        states_by_scene_id = {state.scene_id: state for state in job.scene_asset_states}

        def _ready(scene: Scene) -> bool:
            state = states_by_scene_id.get(str(scene.id))
            return state is not None and state.is_ready

        if all(_ready(scene) for scene in job.scenes):
            return JourneyCheckpoint(
                label="Assets", status=JourneyCheckpointStatus.APPROVED
            )

        has_failure = any(
            state.status in _FAILED_ASSET_STATUSES or state.active_failure is not None
            for state in job.scene_asset_states
        )

        if has_failure:
            return JourneyCheckpoint(
                label="Assets", status=JourneyCheckpointStatus.NEEDS_REVISION
            )

        return JourneyCheckpoint(label="Assets", status=JourneyCheckpointStatus.WAITING)

    @staticmethod
    def _audio_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        if job.audio_timeline is None:
            return JourneyCheckpoint(
                label="Voice & Audio", status=JourneyCheckpointStatus.NOT_STARTED
            )

        return JourneyCheckpoint(
            label="Voice & Audio", status=JourneyCheckpointStatus.APPROVED
        )

    @staticmethod
    def _timeline_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        if job.video_timeline is None:
            return JourneyCheckpoint(
                label="Timeline", status=JourneyCheckpointStatus.NOT_STARTED
            )

        return JourneyCheckpoint(
            label="Timeline", status=JourneyCheckpointStatus.APPROVED
        )

    @staticmethod
    def _render_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        if job.render_result is None:
            return JourneyCheckpoint(
                label="Render", status=JourneyCheckpointStatus.NOT_STARTED
            )

        if (
            job.render_result.status == RenderStatus.FAILED
            or not job.render_result.success
        ):
            return JourneyCheckpoint(
                label="Render", status=JourneyCheckpointStatus.NEEDS_REVISION
            )

        return JourneyCheckpoint(
            label="Render", status=JourneyCheckpointStatus.APPROVED
        )

    @staticmethod
    def _seo_checkpoint(seo_package: SEOPackage | None) -> JourneyCheckpoint:
        status = (
            JourneyCheckpointStatus.APPROVED
            if seo_package is not None
            else JourneyCheckpointStatus.NOT_STARTED
        )

        return JourneyCheckpoint(label="SEO Package", status=status)

    @staticmethod
    def _thumbnail_checkpoint(
        thumbnail: ThumbnailArtifact | None,
    ) -> JourneyCheckpoint:
        status = (
            JourneyCheckpointStatus.APPROVED
            if thumbnail is not None
            else JourneyCheckpointStatus.NOT_STARTED
        )

        return JourneyCheckpoint(label="Thumbnail", status=status)

    @staticmethod
    def _final_export_checkpoint(
        final_export: FinalExportPackage | None,
    ) -> JourneyCheckpoint:
        status = (
            JourneyCheckpointStatus.APPROVED
            if final_export is not None
            else JourneyCheckpointStatus.NOT_STARTED
        )

        return JourneyCheckpoint(label="Final Export", status=status)
