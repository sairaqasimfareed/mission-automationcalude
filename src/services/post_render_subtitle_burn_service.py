from __future__ import annotations

from pathlib import Path

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_input import (
    FFmpegInputBinding,
    FFmpegInputMediaType,
    FFmpegInputPlan,
)
from src.models.render_failure_diagnosis import classify_render_failure
from src.models.render_result import RenderResult, RenderStatus
from src.services.ffmpeg_capability_service import FFmpegCapabilityService
from src.services.ffmpeg_execution_service import (
    CancellationCheck,
    FFmpegExecutionService,
    ProgressCallback,
)
from src.services.production_render_service import ProductionRenderService
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

# Matches SubtitleExecutionService/VideoFilterTranslationService's own
# "subtitle.default" style exactly (REQ-5's genre-aware subtitle
# styling is not built yet - reusing today's one real default rather
# than inventing a second, parallel style definition).
_DEFAULT_SUBTITLE_PRESET_ID = "subtitle.default"


class PostRenderSubtitleBurnService:
    """
    REQ-0: burn a resolved list of AbsoluteSubtitleCue entries onto an
    already-finished video (REQ-00 Stage 2's own output) as one final,
    standalone pass - the architectural pattern already proven by
    ExportVariantRenderService (CTA/watermark end-card) and
    AudioMuxRenderService (Stage 2 itself): build an FFmpegCommandPlan
    by hand, execute directly via FFmpegExecutionService, no
    RenderGraph/FilterGraph/FFmpegCommandBuilderService involved (that
    machinery exists for a full scene/camera/effect/animation
    composite, not a flat chain of drawtext filters over one already-
    finished video).

    Reuses VideoFilterTranslationService's own proven subtitle
    drawtext building blocks (text-file caching that sidesteps a real,
    already-found inline-escaping bug; cross-platform font fallback;
    the "subtitle.default" style) rather than a second, parallel
    implementation.

    Audio passes through untouched (-c:a copy) - this pass only ever
    touches video pixels.
    """

    def __init__(
        self,
        *,
        capability_service: FFmpegCapabilityService | None = None,
        execution_service: FFmpegExecutionService | None = None,
    ) -> None:
        self._capability_service = capability_service or FFmpegCapabilityService()

        self._execution_service = execution_service or FFmpegExecutionService()

    def burn(
        self,
        *,
        input_video_file: str,
        cues: list[AbsoluteSubtitleCue],
        output_file: str,
        video_duration_seconds: float,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        if not cues:
            raise ValueError(
                "Post-render subtitle burn-in requires " "at least one cue."
            )

        if video_duration_seconds <= 0.0:
            raise ValueError(
                "Post-render subtitle burn-in requires " "positive video duration."
            )

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Subtitle burn-in output file cannot be empty.")

        target_output_file = Path(cleaned_output_file).as_posix()

        staging_output_file = ProductionRenderService._staging_output_file(
            target_output_file
        )

        resolved_config = self._capability_service.resolve()

        style = VideoFilterTranslationService._subtitle_style(
            _DEFAULT_SUBTITLE_PRESET_ID
        )

        font_file = VideoFilterTranslationService._resolve_subtitle_font_file()

        if font_file is not None:
            style = {**style, "fontfile": f"'{font_file}'"}

        clauses: list[str] = []
        current_label = "0:v"

        for index, cue in enumerate(cues):
            output_label = "video_final" if index == len(cues) - 1 else f"sub_{index}"

            options = {
                **style,
                "textfile": (
                    "'"
                    + VideoFilterTranslationService._write_subtitle_text_file(cue.text)
                    + "'"
                ),
                "enable": VideoFilterTranslationService._enable_expression(
                    cue.start_seconds, cue.end_seconds
                ),
            }

            options_text = ":".join(f"{key}={value}" for key, value in options.items())

            clauses.append(f"[{current_label}]drawtext={options_text}[{output_label}]")

            current_label = output_label

        filter_complex = ";".join(clauses)

        input_binding = FFmpegInputBinding(
            input_index=0,
            render_node_id="subtitle_burn_source",
            media_type=FFmpegInputMediaType.VIDEO,
            source_file=input_video_file,
            stream_label="0:v",
        )

        input_plan = FFmpegInputPlan(
            bindings=[input_binding],
            input_count=1,
            video_input_count=1,
            audio_input_count=0,
        )

        arguments = [
            "-y",
            "-i",
            input_video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[video_final]",
            "-map",
            "0:a",
            "-c:v",
            resolved_config.selected_video_codec,
        ]

        if resolved_config.selected_video_codec in {"libx264", "libx265"}:
            arguments.extend(
                [
                    "-preset",
                    resolved_config.config.preset,
                    "-crf",
                    str(resolved_config.config.crf),
                ]
            )

        arguments.extend(["-pix_fmt", resolved_config.config.pixel_format.value])
        arguments.extend(["-c:a", "copy"])
        arguments.append(staging_output_file)

        command_plan = FFmpegCommandPlan(
            executable=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label="video_final",
            audio_output_label="source_audio",
            output_file=staging_output_file,
            arguments=arguments,
        )

        try:
            execution_result = self._execution_service.execute(
                command_plan,
                total_duration_seconds=video_duration_seconds,
                timeout_seconds=resolved_config.config.timeout_seconds,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )
        except Exception:
            ProductionRenderService._cleanup_staging_file(staging_output_file)

            raise

        ffmpeg_command = (
            list(execution_result.ffmpeg_command)
            if isinstance(execution_result.ffmpeg_command, list)
            else []
        )

        if execution_result.success:
            completed_staging_file = execution_result.output_file

            if completed_staging_file is None:
                raise RuntimeError(
                    "Successful FFmpeg execution " "did not provide an output file."
                )

            promoted_output_file = ProductionRenderService._promote_staged_output(
                staging_output_file=completed_staging_file,
                target_output_file=target_output_file,
            )

            return RenderResult(
                success=True,
                output_file=promoted_output_file,
                render_engine="ffmpeg",
                render_time_seconds=execution_result.elapsed_seconds,
                duration_seconds=int(video_duration_seconds),
                status=RenderStatus.COMPLETED,
                ffmpeg_command=ffmpeg_command,
                exit_code=execution_result.exit_code,
                selected_video_codec=resolved_config.selected_video_codec,
            )

        error_message = execution_result.error_message or (
            "FFmpeg execution returned " "an unsuccessful result."
        )

        ProductionRenderService._cleanup_staging_file(staging_output_file)

        execution_metadata = execution_result.metadata

        failure_stage = (
            execution_metadata.get("failure_stage")
            if isinstance(execution_metadata, dict)
            else None
        )

        return RenderResult(
            success=False,
            output_file=None,
            render_engine="ffmpeg",
            render_time_seconds=execution_result.elapsed_seconds,
            duration_seconds=int(video_duration_seconds),
            status=RenderStatus.FAILED,
            error_message=error_message,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
            failure_category=classify_render_failure(failure_stage),
            selected_video_codec=resolved_config.selected_video_codec,
        )
