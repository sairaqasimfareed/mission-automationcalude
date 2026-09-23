from __future__ import annotations

import time

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.render_result import RenderResult
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.audio_inclusion_filter_service import (
    filter_audio_timeline_for_mux,
)
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.render_service import RenderService
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.top10_countdown_service import Top10CountdownService


class RenderPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for render execution.

    The stage remains orchestration glue only.

    When a ProductionRenderService is supplied, the stage executes the
    prepared VideoJob through the real FFmpeg production render boundary.

    When no production renderer is supplied, the existing RenderService
    path remains available for backward compatibility with legacy and
    isolated dry-run workflows.
    """

    def __init__(
        self,
        *,
        render_service: RenderService | None = None,
        production_render_service: ProductionRenderService | None = None,
        voice_blueprints: list[ResolvedVoiceBlueprint] | None = None,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        audio_inclusion_preferences: AudioInclusionPreferences | None = None,
        subtitles_enabled: bool = True,
        genre_id: str | None = None,
        top10_countdown_service: Top10CountdownService | None = None,
    ) -> None:
        if production_render_service is not None and not voice_blueprints:
            raise ValueError(
                "Production render stage requires " "resolved voice blueprints."
            )

        self._render_service = render_service or RenderService()

        self._production_render_service = production_render_service

        self._voice_blueprints = list(voice_blueprints or [])

        self._transition_duration_seconds = transition_duration_seconds

        # REQ-3 (cinematic letterboxing), 2026-09-22: the caller's own
        # already-resolved choice (genre default + real per-project
        # override - see RenderWorkflowStageFactory.build()), forwarded
        # unchanged to every real render entry point below.
        self._letterbox_enabled = letterbox_enabled

        # REQ-13 (audio inclusion toggle UI), 2026-09-23: the real
        # per-project VideoJob.audio_inclusion_preferences (see
        # RenderWorkflowStageFactory.build()) - defaults to a fresh
        # AudioInclusionPreferences() when the caller passes nothing,
        # which reproduces today's exact real behavior (every generated
        # track type included, native-clip audio excluded - see that
        # model's own docstring).
        self._audio_inclusion_preferences = (
            audio_inclusion_preferences or AudioInclusionPreferences()
        )

        # Subtitle on/off toggle, 2026-09-23: the real per-project
        # VideoJob.subtitles_enabled (see RenderWorkflowStageFactory.
        # build()), forwarded unchanged to the real render entry
        # point. Defaults to True, reproducing every render's real
        # prior behavior.
        self._subtitles_enabled = subtitles_enabled

        # REQ-12 (top10 countdown rank cards), 2026-09-23: the real
        # genre id this render was requested for (see RenderWorkflow
        # StageFactory.build()'s own genre_id parameter) - needed only
        # to build a real SEOContext for a top10 countdown render, see
        # _execute_top10_countdown_render() below. None reproduces
        # every prior caller's exact behavior (never read otherwise).
        self._genre_id = genre_id

        # None means top10 countdown rendering stays unavailable for
        # this stage - see RenderWorkflowStageFactory's own top10_
        # countdown_service docstring for why. A genre.top10 job then
        # renders through the normal composite path below with no
        # countdown splice, rather than failing.
        self._top10_countdown_service = top10_countdown_service

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the pipeline identifier for this adapter."""

        return PipelineStageName.RENDER

    @property
    def production_render_enabled(
        self,
    ) -> bool:
        """Return whether real production rendering is configured."""

        return self._production_render_service is not None

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Render the VideoJob's prepared timelines.

        Expected orchestration-state errors are normalized into failed
        StageResults.

        Unexpected renderer exceptions intentionally cross this adapter
        boundary so RenderOrchestratorService can apply its existing
        exception-normalization policy.
        """

        start_time = time.perf_counter()

        timeline = context.job.video_timeline

        if timeline is None:
            return self._failed_result(
                started_at=start_time,
                error_message=("Render stage requires " "VideoJob.video_timeline."),
            )

        if not (timeline.items or timeline.clips):
            return self._failed_result(
                started_at=start_time,
                error_message=("Render stage requires a " "non-empty video timeline."),
            )

        if self.production_render_enabled:
            render_result = self._execute_production_render(
                context=context,
            )
        else:
            render_result = self._render_service.render(timeline)

        context.job.render_result = render_result

        return self._stage_result_from_render(
            render_result=render_result,
            started_at=start_time,
        )

    def _execute_production_render(
        self,
        *,
        context: StageContext,
    ) -> RenderResult:
        """Execute the real production rendering boundary."""

        production_render_service = self._production_render_service

        if production_render_service is None:
            raise RuntimeError("Production render service " "is not configured.")

        video_timeline = context.job.video_timeline

        if video_timeline is None:
            raise RuntimeError("Production render requires " "VideoJob.video_timeline.")

        audio_timeline = context.job.audio_timeline

        if audio_timeline is None:
            raise ValueError(
                "Production render stage requires " "VideoJob.audio_timeline."
            )

        # REQ-13 (audio inclusion toggle UI): apply the real per-project
        # mux-time filter BEFORE rendering - voiceover/music/SFX always
        # generate unconditionally (see AudioInclusionPreferences' own
        # docstring), only what actually reaches the real render is
        # gated here. An empty result (every toggle off, or nothing
        # generated yet) is not an error - RenderGraphBuilderService/
        # FilterGraphBuilderService already treat zero real audio
        # tracks as a legitimate, silently-handled "render without
        # audio" case (confirmed via REQ-00 Stage 1's own relaxation of
        # what used to be an unconditional audio-nodes requirement).
        audio_timeline = filter_audio_timeline_for_mux(
            audio_timeline=audio_timeline,
            preferences=self._audio_inclusion_preferences,
        )

        if not self._voice_blueprints:
            raise ValueError(
                "Production render stage requires " "resolved voice blueprints."
            )

        progress_callback = context.services.get("progress_callback")

        # REQ-12 (top10 countdown rank cards), 2026-09-23: a job whose
        # scenes carry a real Scene.list_rank (assigned earlier by
        # TopTenRankAssignmentService) renders through
        # Top10CountdownService instead of the normal composite path
        # below - it REPLACES the render rather than running alongside
        # it (each rank's own card render + hard-cut splice IS the
        # render for this job). self._top10_countdown_service is None
        # whenever this runtime never configured one (see RenderWork
        # flowStageFactory's own docstring) - such a job silently
        # falls through to the normal composite render below, with no
        # countdown splice, rather than failing.
        if self._top10_countdown_service is not None and any(
            scene.list_rank is not None for scene in context.job.scenes
        ):
            if self._genre_id is None:
                raise RuntimeError(
                    "Top10 countdown rendering requires a real genre id."
                )

            seo_context = SEOContextBuilder().build(
                context.job,
                genre_id=self._genre_id,
            )

            voice_profile_id = self._voice_blueprints[0].profile.resolved_profile_id

            return self._top10_countdown_service.build(
                scenes=context.job.scenes,
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=self._voice_blueprints,
                seo_context=seo_context,
                voice_profile_id=voice_profile_id,
                output_file=production_render_service.DEFAULT_OUTPUT_FILE,
                image_override=(context.job.top10_countdown_background_image_path),
                include_numbering_voiceover=(
                    context.job.top10_countdown_include_numbering_voiceover
                ),
                transition_duration_seconds=self._transition_duration_seconds,
                letterbox_enabled=self._letterbox_enabled,
                progress_callback=progress_callback,
            )

        return production_render_service.render(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=(self._voice_blueprints),
            progress_callback=progress_callback,
            transition_duration_seconds=self._transition_duration_seconds,
            letterbox_enabled=self._letterbox_enabled,
            include_subtitles=self._subtitles_enabled,
        )

    def execute_video_only(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        REQ-00 Stage 1: render video-only (no audio, no subtitles
        muxed in), storing the result on
        VideoJob.video_only_render_result - NOT render_result, which
        still means the real, final composite render (Stage 2's audio
        mux and Stage 3's subtitle burn-in don't exist yet, so
        render_result stays the only thing anything today treats as
        "the finished video").

        Deliberately NOT called by execute() itself, and
        RenderWorkflowStageFactory.build() does not add any separate
        stage for it - a caller that wants a video-only render takes
        the same RenderPipelineStage instance build() already returns
        (the one that will run the real composite render) and calls
        this method on it directly, reusing its already-configured
        production_render_service/voice_blueprints/
        transition_duration_seconds rather than needing a second,
        separately-wired instance. No real caller exists yet (REQ-0A's
        review gate, Stage 2's own mux service are both unbuilt) - this
        makes Stage 1 reachable through the same pipeline-stage
        abstraction the rest of the app already understands, ahead of
        those being built, without changing the pipeline's own default
        behavior at all.
        """

        start_time = time.perf_counter()

        if self._production_render_service is None:
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Video-only render requires a configured "
                    "production render service."
                ),
            )

        video_timeline = context.job.video_timeline

        if video_timeline is None:
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Video-only render stage requires " "VideoJob.video_timeline."
                ),
            )

        if not (video_timeline.items or video_timeline.clips):
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Video-only render stage requires a " "non-empty video timeline."
                ),
            )

        audio_timeline = context.job.audio_timeline

        if audio_timeline is None:
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Video-only render stage requires " "VideoJob.audio_timeline."
                ),
            )

        if not self._voice_blueprints:
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Video-only render stage requires " "resolved voice blueprints."
                ),
            )

        progress_callback = context.services.get("progress_callback")

        render_result = self._production_render_service.render_video_only(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=self._voice_blueprints,
            progress_callback=progress_callback,
            transition_duration_seconds=self._transition_duration_seconds,
            letterbox_enabled=self._letterbox_enabled,
        )

        context.job.video_only_render_result = render_result

        return self._stage_result_from_render(
            render_result=render_result,
            started_at=start_time,
        )

    def _stage_result_from_render(
        self,
        *,
        render_result: RenderResult,
        started_at: float,
    ) -> StageResult:
        """
        Translate the provider-independent RenderResult into the generic
        pipeline StageResult contract.
        """

        duration_seconds = time.perf_counter() - started_at

        metadata: dict[
            str,
            object,
        ] = {
            "render_engine": (render_result.render_engine),
            "output_file": (render_result.output_file),
            "render_time_seconds": (render_result.render_time_seconds),
            "render_duration_seconds": (render_result.duration_seconds),
            "production_render": (self.production_render_enabled),
        }

        if render_result.success:
            return StageResult(
                stage=self.stage_name,
                status=(PipelineStageStatus.COMPLETED),
                duration_seconds=(duration_seconds),
                progress_percent=100,
                warnings=list(render_result.warnings),
                errors=[],
                metadata=metadata,
            )

        error_message = render_result.error_message or (
            "Render service returned " "an unsuccessful result."
        )

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(duration_seconds),
            progress_percent=100,
            warnings=list(render_result.warnings),
            errors=[
                error_message,
            ],
            metadata=metadata,
        )

    def _failed_result(
        self,
        *,
        started_at: float,
        error_message: str,
    ) -> StageResult:
        """Create a normalized precondition failure."""

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(time.perf_counter() - started_at),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "render_engine": None,
                "output_file": None,
                "production_render": (self.production_render_enabled),
            },
        )
