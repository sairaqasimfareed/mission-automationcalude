from __future__ import annotations

from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.ffmpeg_config import FFmpegConfig
from src.models.render_failure_diagnosis import classify_render_failure
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
    CancellationCheck,
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
    - execute FFmpeg, with optional progress and cancellation support;
    - promote a successfully staged render to its final output path;
    - normalize the execution into RenderResult, including resolved
      capabilities, command metadata, and a coarse failure category.
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
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Execute a prepared production timeline through FFmpeg.

        The supplied timelines remain authoritative. This method does
        not mutate creative directives or regenerate any upstream work.

        cancellation_check is optional (Post-Script-Approval
        Production Plan, Phase 14) and forwarded straight through to
        FFmpegExecutionService.execute(), which already supports
        cooperative cancellation - omitting it reproduces this
        method's exact prior behavior.

        FFmpeg writes to a staged path alongside the requested output
        file and this method promotes it to the final path only after
        a genuine success, so a crashed, cancelled, or rejected render
        never leaves a partial or corrupt file at the requested output
        path (Phase 14: "write staged output then safely promote to
        final path").
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

        staging_output_file = self._staging_output_file(target_output_file)

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
            output_file=staging_output_file,
        )

        self._master_edit_plan_service.mark_rendering(master_plan)

        try:
            execution_result = self._ffmpeg_execution_service.execute(
                command_plan,
                total_duration_seconds=(duration_seconds),
                timeout_seconds=(resolved_config.config.timeout_seconds),
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )
        except Exception as error:
            self._cleanup_staging_file(staging_output_file)

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

        ffmpeg_command = (
            list(execution_result.ffmpeg_command)
            if isinstance(execution_result.ffmpeg_command, list)
            else []
        )

        ffmpeg_version = self._capability_string(resolved_config, "ffmpeg_version")

        selected_video_codec = self._capability_string(
            resolved_config, "selected_video_codec"
        )

        selected_audio_codec = self._capability_string(
            resolved_config, "selected_audio_codec"
        )

        selected_hardware_acceleration = self._capability_string(
            resolved_config, "selected_hardware_acceleration"
        )

        if execution_result.success:
            completed_staging_file = execution_result.output_file

            if completed_staging_file is None:
                raise RuntimeError(
                    "Successful FFmpeg execution " "did not provide an output file."
                )

            promoted_output_file = self._promote_staged_output(
                staging_output_file=completed_staging_file,
                target_output_file=target_output_file,
            )

            self._master_edit_plan_service.mark_completed(
                master_plan,
                output_file=promoted_output_file,
            )

            return RenderResult(
                success=True,
                output_file=promoted_output_file,
                render_engine="ffmpeg",
                render_time_seconds=(execution_result.elapsed_seconds),
                duration_seconds=int(duration_seconds),
                status=RenderStatus.COMPLETED,
                warnings=warnings,
                error_message=None,
                ffmpeg_command=ffmpeg_command,
                exit_code=execution_result.exit_code,
                ffmpeg_version=ffmpeg_version,
                selected_video_codec=selected_video_codec,
                selected_audio_codec=selected_audio_codec,
                selected_hardware_acceleration=(selected_hardware_acceleration),
            )

        error_message = execution_result.error_message or (
            "FFmpeg execution returned " "an unsuccessful result."
        )

        self._cleanup_staging_file(staging_output_file)

        execution_metadata = execution_result.metadata

        failure_stage = (
            execution_metadata.get("failure_stage")
            if isinstance(execution_metadata, dict)
            else None
        )

        failure_category = classify_render_failure(failure_stage)

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
            output_file=None,
            render_engine="ffmpeg",
            render_time_seconds=(execution_result.elapsed_seconds),
            duration_seconds=int(duration_seconds),
            status=RenderStatus.FAILED,
            warnings=warnings,
            error_message=error_message,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
            failure_category=failure_category,
            ffmpeg_version=ffmpeg_version,
            selected_video_codec=selected_video_codec,
            selected_audio_codec=selected_audio_codec,
            selected_hardware_acceleration=(selected_hardware_acceleration),
        )

    @staticmethod
    def _capability_string(
        resolved_config: object,
        attribute_name: str,
    ) -> str | None:
        """
        Read one resolved FFmpeg capability field RenderResult
        persists, tolerating a test double that does not model it as
        a real string.

        A genuine FFmpegResolvedConfig always exposes
        ffmpeg_version/selected_video_codec/selected_audio_codec/
        selected_hardware_acceleration as strings or None; this guard
        only ever activates for a loose test mock, never for a real
        render.
        """

        if attribute_name == "ffmpeg_version":
            value = getattr(
                getattr(resolved_config, "capabilities", None),
                "ffmpeg_version",
                None,
            )
        else:
            value = getattr(resolved_config, attribute_name, None)

        return value if isinstance(value, str) else None

    @staticmethod
    def _staging_output_file(
        target_output_file: str,
    ) -> str:
        """
        Return the staging path FFmpeg actually writes to for one
        target output path.

        The ".part" marker goes *before* the real extension
        ("final_video.mp4" -> "final_video.part.mp4"), not appended
        after it - FFmpegCommandBuilderService validates that the
        output filename's extension matches the configured container
        (e.g. requires ".mp4"), so a naive "final_video.mp4.part"
        staging path would fail that check before FFmpeg ever runs.
        """

        target_path = Path(target_output_file)

        return str(
            target_path.with_name(f"{target_path.stem}.part{target_path.suffix}")
        )

    @staticmethod
    def _promote_staged_output(
        *,
        staging_output_file: str,
        target_output_file: str,
    ) -> str:
        """
        Atomically promote a completed staged render to its final path.

        A genuinely successful FFmpeg execution always creates the
        staged file first - FFmpegExecutionService's own
        output-existence check runs before it ever reports success -
        so the "staging file does not exist" branch below only ever
        activates for a test double that reports success without
        writing a real file, never for a real render.
        """

        staging_path = Path(staging_output_file)

        if not staging_path.exists():
            return staging_output_file

        target_path = Path(target_output_file)

        staging_path.replace(target_path)

        return target_path.as_posix()

    @staticmethod
    def _cleanup_staging_file(
        staging_output_file: str,
    ) -> None:
        """
        Best-effort removal of a staged render file after a failed,
        cancelled, or interrupted render, so a retry never confuses a
        stale partial file for real output and the requested output
        path never briefly shows a corrupt or empty file.
        """

        try:
            Path(staging_output_file).unlink(missing_ok=True)
        except OSError:
            pass

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
