from __future__ import annotations

import time
from pathlib import Path

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.audio_timeline import AudioTimeline
from src.models.render_result import RenderResult
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.video_timeline import VideoTimeline
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
from src.services.audio_mux_render_service import AudioMuxRenderService
from src.services.ffmpeg_execution_service import ProgressCallback
from src.services.post_render_subtitle_burn_service import (
    PostRenderSubtitleBurnService,
)
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.render_service import RenderService
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.subtitle_cue_resolution_service import (
    resolve_absolute_subtitle_cues,
)
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
        audio_mux_render_service: AudioMuxRenderService | None = None,
        subtitle_burn_service: PostRenderSubtitleBurnService | None = None,
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

        # REQ-00 Stage 2 / REQ-0 Stage 3, 2026-09-24: neither service
        # has any external composition-root dependency (each
        # self-constructs its own FFmpegCapabilityService/
        # FFmpegExecutionService), so unlike top10_countdown_service
        # these are not threaded through RenderWorkflowStageFactory -
        # a real default instance is always available. Constructor
        # overrides exist only so _execute_staged_render()'s
        # orchestration can be tested against real service instances
        # without needing real FFmpeg for every test.
        self._audio_mux_render_service = (
            audio_mux_render_service or AudioMuxRenderService()
        )

        self._subtitle_burn_service = (
            subtitle_burn_service or PostRenderSubtitleBurnService()
        )

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

        unfiltered_audio_timeline = context.job.audio_timeline

        if unfiltered_audio_timeline is None:
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
        #
        # unfiltered_audio_timeline (the real, un-gated one) is kept
        # separately rather than overwritten - MasterEditPlanService's
        # render-readiness validation (voice_ready) requires a real
        # voiceover track regardless of what the user chose to mute,
        # and REQ-00 Stage 1's render_video_only() runs that same
        # validation. See _execute_staged_render()'s own docstring for
        # why passing it the filtered timeline would be wrong.
        audio_timeline = filter_audio_timeline_for_mux(
            audio_timeline=unfiltered_audio_timeline,
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

        # REQ-00/REQ-0 staged pipeline swap, 2026-09-24: Stage 1 (video-
        # only) -> conditional Stage 2 (audio mux) -> conditional Stage 3
        # (subtitle burn-in), replacing the old one-shot composite
        # render() below for any job whose command fits one FFmpeg
        # invocation. render_video_only() deliberately does not support
        # command-line-length-driven chunking yet (see its own
        # docstring) - a job long/complex enough to need it raises
        # NotImplementedError before any FFmpeg execution starts (no
        # partial file to clean up), and falls back to the old,
        # still-fully-functional composite render() unchanged below.
        try:
            return self._execute_staged_render(
                production_render_service=production_render_service,
                video_timeline=video_timeline,
                unfiltered_audio_timeline=unfiltered_audio_timeline,
                muxed_audio_timeline=audio_timeline,
                progress_callback=progress_callback,
            )
        except NotImplementedError:
            pass

        return production_render_service.render(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=(self._voice_blueprints),
            progress_callback=progress_callback,
            transition_duration_seconds=self._transition_duration_seconds,
            letterbox_enabled=self._letterbox_enabled,
            include_subtitles=self._subtitles_enabled,
        )

    def _execute_staged_render(
        self,
        *,
        production_render_service: ProductionRenderService,
        video_timeline: VideoTimeline,
        unfiltered_audio_timeline: AudioTimeline,
        muxed_audio_timeline: AudioTimeline,
        progress_callback: ProgressCallback | None,
    ) -> RenderResult:
        """
        REQ-00 Stage 1 -> conditional Stage 2 -> conditional REQ-0
        Stage 3.

        Stage 1 always receives unfiltered_audio_timeline, the job's
        real, un-gated audio timeline - MasterEditPlanService's render-
        readiness validation (voice_ready) requires a real voiceover
        track regardless of what will actually be muxed in (voiceover/
        music/SFX generation is unconditional - see
        AudioInclusionPreferences' own docstring - only mux-time
        inclusion is toggled), and Stage 1's own render graph never
        builds audio nodes anyway (render_video_only() always passes
        include_audio=False internally), so what is IN that timeline
        has zero effect on Stage 1's actual output pixels.

        muxed_audio_timeline is the REQ-13 mux-time-filtered timeline
        (filter_audio_timeline_for_mux()'s own result) - it alone
        decides whether Stage 2 runs at all. Every toggle off (a
        legitimate silent render, not an error) means muxed_audio_
        timeline.tracks is empty: AudioMuxRenderService.mux() itself
        hard-rejects an empty track list, so Stage 2 is skipped
        entirely and Stage 1's own raw output (which already has zero
        audio streams by construction) is used directly wherever
        Stage 2's result would otherwise have been used.
        """

        target_output_file = production_render_service.output_file

        stage1_output_file = self._stage_output_file(target_output_file, "stage1")

        stage1_result = production_render_service.render_video_only(
            video_timeline=video_timeline,
            audio_timeline=unfiltered_audio_timeline,
            voice_blueprints=self._voice_blueprints,
            output_file=stage1_output_file,
            progress_callback=progress_callback,
            transition_duration_seconds=self._transition_duration_seconds,
            letterbox_enabled=self._letterbox_enabled,
        )

        if not stage1_result.success:
            return stage1_result

        has_muxed_audio = bool(muxed_audio_timeline.tracks)

        cues = (
            resolve_absolute_subtitle_cues(
                video_timeline=video_timeline,
                voice_blueprints=self._voice_blueprints,
                scene_timings=stage1_result.scene_timings,
                transition_duration_seconds=self._transition_duration_seconds,
            )
            if self._subtitles_enabled
            else []
        )

        needs_subtitle_burn = bool(cues)

        if has_muxed_audio:
            stage2_output_file = (
                self._stage_output_file(target_output_file, "stage2")
                if needs_subtitle_burn
                else target_output_file
            )

            stage2_result = self._audio_mux_render_service.mux(
                video_only_render_result=stage1_result,
                audio_timeline=muxed_audio_timeline,
                output_file=stage2_output_file,
                progress_callback=progress_callback,
            )

            if not stage2_result.success:
                return stage2_result
        else:
            stage2_result = stage1_result

        if needs_subtitle_burn:
            if stage2_result.output_file is None:
                raise RuntimeError(
                    "Successful staged render did not " "provide an output file."
                )

            return self._subtitle_burn_service.burn(
                input_video_file=stage2_result.output_file,
                cues=cues,
                output_file=target_output_file,
                video_duration_seconds=float(stage2_result.duration_seconds),
                has_audio=has_muxed_audio,
                progress_callback=progress_callback,
            )

        # stage2_result is the final result. When it was never routed
        # through Stage 2's own mux (has_muxed_audio False) it is still
        # sitting at stage1_output_file rather than the real target -
        # promote it now, reusing ProductionRenderService's own proven
        # staged-file-promotion primitive rather than a second one.
        if stage2_result.output_file != target_output_file:
            promoted_output_file = ProductionRenderService._promote_staged_output(
                staging_output_file=(stage2_result.output_file or stage1_output_file),
                target_output_file=target_output_file,
            )

            return stage2_result.model_copy(
                update={"output_file": promoted_output_file}
            )

        return stage2_result

    @staticmethod
    def _stage_output_file(target_output_file: str, stage_name: str) -> str:
        """
        Return an intermediate per-stage output path derived from the
        job's real final output path (e.g. "final_video.mp4" ->
        "final_video.stage1.mp4") - distinct from ProductionRender
        Service._staging_output_file()'s own ".part" marker (that one
        is FFmpeg's own in-progress write target for a single stage,
        this one distinguishes one whole stage's finished output from
        another's within the same staged render).
        """

        target_path = Path(target_output_file)

        return target_path.with_name(
            f"{target_path.stem}.{stage_name}{target_path.suffix}"
        ).as_posix()

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
