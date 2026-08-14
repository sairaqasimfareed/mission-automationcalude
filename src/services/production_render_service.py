from __future__ import annotations

from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.ffmpeg_config import FFmpegConfig
from src.models.render_result import RenderResult, RenderStatus
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.video_timeline import VideoTimeline
from src.services.animation_execution_service import (
    AnimationExecutionService,
)
from src.services.camera_execution_service import (
    CameraExecutionService,
)
from src.services.effect_execution_service import (
    EffectExecutionService,
)
from src.services.ffmpeg_capability_service import (
    FFmpegCapabilityService,
)
from src.services.ffmpeg_command_builder_service import (
    FFmpegCommandBuilderService,
)
from src.services.ffmpeg_execution_service import (
    FFmpegExecutionService,
    ProgressCallback,
)
from src.services.filter_graph_builder_service import (
    FilterGraphBuilderService,
)
from src.services.master_edit_plan_service import (
    MasterEditPlanService,
)
from src.services.render_graph_builder_service import (
    RenderGraphBuilderService,
)
from src.services.subtitle_execution_service import (
    SubtitleExecutionService,
)
from src.services.transition_execution_service import (
    TransitionExecutionService,
)


class ProductionRenderService:
    """
    Execute one prepared video job through the real FFmpeg render stack.

    This service is the production rendering boundary between the
    provider-independent editing/timeline architecture and FFmpeg.

    It does not create scenes, generate assets, resolve editing
    directives, generate voice, or own pipeline orchestration.

    Its responsibilities are limited to:

    - combine prepared video/audio timelines into a master edit plan;
    - build renderer-independent execution plans;
    - build the renderer-independent render graph;
    - resolve local FFmpeg capabilities;
    - build the FFmpeg filter graph;
    - build the deterministic FFmpeg command plan;
    - execute FFmpeg;
    - normalize the execution into RenderResult.
    """

    DEFAULT_OUTPUT_FILE = "outputs/final_video.mp4"

    def __init__(
        self,
        *,
        master_edit_plan_service: MasterEditPlanService | None = None,
        transition_execution_service: TransitionExecutionService | None = None,
        effect_execution_service: EffectExecutionService | None = None,
        subtitle_execution_service: SubtitleExecutionService | None = None,
        camera_execution_service: CameraExecutionService | None = None,
        animation_execution_service: AnimationExecutionService | None = None,
        render_graph_builder_service: RenderGraphBuilderService | None = None,
        ffmpeg_capability_service: FFmpegCapabilityService | None = None,
        filter_graph_builder_service: FilterGraphBuilderService | None = None,
        ffmpeg_command_builder_service: FFmpegCommandBuilderService | None = None,
        ffmpeg_execution_service: FFmpegExecutionService | None = None,
        ffmpeg_config: FFmpegConfig | None = None,
        output_file: str = DEFAULT_OUTPUT_FILE,
    ) -> None:
        self._master_edit_plan_service = (
            master_edit_plan_service or MasterEditPlanService()
        )

        self._transition_execution_service = (
            transition_execution_service or TransitionExecutionService()
        )

        self._effect_execution_service = (
            effect_execution_service or EffectExecutionService()
        )

        self._subtitle_execution_service = (
            subtitle_execution_service or SubtitleExecutionService()
        )

        self._camera_execution_service = (
            camera_execution_service or CameraExecutionService()
        )

        self._animation_execution_service = (
            animation_execution_service or AnimationExecutionService()
        )

        self._render_graph_builder_service = (
            render_graph_builder_service or RenderGraphBuilderService()
        )

        self._ffmpeg_capability_service = (
            ffmpeg_capability_service or FFmpegCapabilityService()
        )

        self._filter_graph_builder_service = (
            filter_graph_builder_service or FilterGraphBuilderService()
        )

        self._ffmpeg_command_builder_service = (
            ffmpeg_command_builder_service or FFmpegCommandBuilderService()
        )

        self._ffmpeg_execution_service = (
            ffmpeg_execution_service or FFmpegExecutionService()
        )

        self._ffmpeg_config = ffmpeg_config or FFmpegConfig()

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Production render output file " "cannot be empty.")

        self._output_file = Path(cleaned_output_file).as_posix()

    @property
    def output_file(self) -> str:
        """Return the configured default output file."""

        return self._output_file

    @property
    def ffmpeg_config(self) -> FFmpegConfig:
        """Return the configured FFmpeg preferences."""

        return self._ffmpeg_config

    def render(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        output_file: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RenderResult:
        """
        Execute a prepared production timeline through FFmpeg.

        The supplied timelines remain authoritative. This method does
        not mutate creative directives or regenerate any upstream work.
        """

        duration_seconds = video_timeline.calculate_duration()

        if duration_seconds <= 0.0:
            raise ValueError(
                "Production rendering requires " "positive video duration."
            )

        if not voice_blueprints:
            raise ValueError(
                "Production rendering requires " "resolved voice blueprints."
            )

        target_output_file = self._resolve_output_file(output_file)

        master_plan = self._master_edit_plan_service.build(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
        )

        self._master_edit_plan_service.validate_render_ready(
            master_plan,
            refresh_first=True,
        )

        transition_plan = self._transition_execution_service.build_plan(
            video_timeline,
            track_index=0,
            include_timeline_in=True,
            include_timeline_out=True,
            validate_timeline=True,
            mark_ready=True,
        )

        effect_plan = self._effect_execution_service.build_plan(
            video_timeline,
            track_index=None,
            validate_timeline=True,
            mark_ready=True,
        )

        subtitle_plan = self._subtitle_execution_service.build_plan(
            video_timeline,
            voice_blueprints=voice_blueprints,
            mark_ready=True,
        )

        camera_plan = self._camera_execution_service.build_plan(
            video_timeline,
            track_index=None,
            validate_timeline=True,
            include_static=True,
            mark_ready=True,
        )

        animation_plan = self._animation_execution_service.build_plan(
            video_timeline,
            track_index=None,
            validate_timeline=True,
            mark_ready=True,
        )

        render_graph = self._render_graph_builder_service.build(
            master_plan=master_plan,
            transition_plan=transition_plan,
            effect_plan=effect_plan,
            subtitle_plan=subtitle_plan,
            camera_plan=camera_plan,
            animation_plan=animation_plan,
            mark_ready=True,
        )

        resolved_config = self._ffmpeg_capability_service.resolve(self._ffmpeg_config)

        filter_graph = self._filter_graph_builder_service.build(
            render_graph=render_graph,
            resolved_config=resolved_config,
        )

        command_plan = self._ffmpeg_command_builder_service.build(
            render_graph=render_graph,
            filter_graph=filter_graph,
            resolved_config=resolved_config,
            output_file=target_output_file,
        )

        self._master_edit_plan_service.mark_rendering(master_plan)

        try:
            execution_result = self._ffmpeg_execution_service.execute(
                command_plan,
                total_duration_seconds=(duration_seconds),
                timeout_seconds=(resolved_config.config.timeout_seconds),
                progress_callback=progress_callback,
            )
        except Exception as error:
            self._master_edit_plan_service.mark_failed(
                master_plan,
                error_message=str(error),
                failure_metadata={
                    "renderer": "ffmpeg",
                    "output_file": (target_output_file),
                },
            )

            raise

        warnings = self._unique_warnings(
            [
                *master_plan.warnings,
                *render_graph.warnings,
                *resolved_config.warnings,
            ]
        )

        if execution_result.success:
            completed_output_file = execution_result.output_file

            if completed_output_file is None:
                raise RuntimeError(
                    "Successful FFmpeg execution " "did not provide an output file."
                )

            self._master_edit_plan_service.mark_completed(
                master_plan,
                output_file=completed_output_file,
            )

            return RenderResult(
                success=True,
                output_file=completed_output_file,
                render_engine="ffmpeg",
                render_time_seconds=(execution_result.elapsed_seconds),
                duration_seconds=int(duration_seconds),
                status=RenderStatus.COMPLETED,
                warnings=warnings,
                error_message=None,
            )

        error_message = execution_result.error_message or (
            "FFmpeg execution returned " "an unsuccessful result."
        )

        self._master_edit_plan_service.mark_failed(
            master_plan,
            error_message=error_message,
            failure_metadata={
                "renderer": "ffmpeg",
                "output_file": (target_output_file),
                "exit_code": (execution_result.exit_code),
                "execution_status": (execution_result.status.value),
            },
        )

        return RenderResult(
            success=False,
            output_file=(execution_result.output_file),
            render_engine="ffmpeg",
            render_time_seconds=(execution_result.elapsed_seconds),
            duration_seconds=int(duration_seconds),
            status=RenderStatus.FAILED,
            warnings=warnings,
            error_message=error_message,
        )

    def _resolve_output_file(
        self,
        output_file: str | None,
    ) -> str:
        """Return a normalized render output path."""

        if output_file is None:
            return self._output_file

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Production render output file " "cannot be empty.")

        return Path(cleaned_output_file).as_posix()

    @staticmethod
    def _unique_warnings(
        warnings: list[str],
    ) -> list[str]:
        """Return normalized unique warnings."""

        result: list[str] = []

        for warning in warnings:
            cleaned_warning = warning.strip()

            if cleaned_warning and cleaned_warning not in result:
                result.append(cleaned_warning)

        return result
