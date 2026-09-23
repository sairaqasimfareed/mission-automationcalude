from __future__ import annotations

from pathlib import Path

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_input import (
    FFmpegInputBinding,
    FFmpegInputMediaType,
    FFmpegInputPlan,
)
from src.models.render_failure_diagnosis import classify_render_failure
from src.models.render_result import RenderResult, RenderStatus
from src.models.thumbnail import ThumbnailTextPosition
from src.models.title_card_text_style import TitleCardTextStyle
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

# REQ-4 (opening title card), 2026-09-22: real timing locked during
# design discussion - a two-beat "brand stamp -> title reveal"
# structure (same convention as a studio vanity card before a movie
# title), weighted toward the title since that's the part a viewer
# actually needs to read, not split evenly.
TOTAL_DURATION_SECONDS = 3.0
_BEAT_1_START_SECONDS = 0.0
_BEAT_1_END_SECONDS = 1.0
_BEAT_2_START_SECONDS = 1.2
_BEAT_2_END_SECONDS = TOTAL_DURATION_SECONDS
_FADE_SECONDS = 0.2

_BASE_TITLE_FONTSIZE = 96
_BASE_CHANNEL_FONTSIZE = 44
_BASE_PRESENTS_FONTSIZE = 28

_SAFE_MARGIN_FRACTION = 0.08


class TitleCardRenderService:
    """
    REQ-4 (opening title card): build one standalone, real 3-second
    video+audio clip - a dedicated generated background image, a
    genre-flavored music sting, and two timed text beats - ready to be
    concat-prepended onto an already-finished render by
    TitleCardPrependService.

    Deliberately NOT built on RenderGraph/FilterGraph/
    FFmpegCommandBuilderService - none of that machinery's per-scene
    concepts (crossfades, scene timing, editing directives) apply to
    one static image held for a fixed duration. Mirrors
    AudioMuxRenderService's own proven shape instead: hand-built
    FFmpegCommandPlan, direct FFmpegExecutionService.execute() call.

    Reuses VideoFilterTranslationService's own drawtext building
    blocks (font resolution, text-file writing, path escaping, enable-
    expression construction) exactly as PostRenderSubtitleBurnService
    already does, rather than a second implementation.
    """

    def __init__(
        self,
        *,
        capability_service: FFmpegCapabilityService | None = None,
        execution_service: FFmpegExecutionService | None = None,
    ) -> None:
        self._capability_service = capability_service or FFmpegCapabilityService()

        self._execution_service = execution_service or FFmpegExecutionService()

    def build(
        self,
        *,
        image_file: str,
        music_file: str | None,
        channel_name: str,
        title_text: str,
        text_style: TitleCardTextStyle,
        position: ThumbnailTextPosition,
        width: int,
        height: int,
        frame_rate: float,
        output_file: str,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Render the standalone title-card clip.

        music_file is optional - None (music generation failed, or was
        never requested) produces a real silent audio stream instead
        of no audio stream at all, so the clip always has exactly one
        video and one audio stream, matching what concatenation with
        the main render requires either way.
        """

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Title card render output file cannot be empty.")

        target_output_file = Path(cleaned_output_file).as_posix()

        staging_output_file = ProductionRenderService._staging_output_file(
            target_output_file
        )

        resolved_config = self._capability_service.resolve()

        pixel_format = str(resolved_config.config.pixel_format.value)

        display_title = title_text.upper() if text_style.uppercase else title_text

        filter_complex, video_output_label, audio_output_label = (
            self._build_filter_complex(
                channel_name=channel_name,
                title_text=display_title,
                text_style=text_style,
                position=position,
                width=width,
                height=height,
                frame_rate=frame_rate,
                pixel_format=pixel_format,
                has_music=music_file is not None,
            )
        )

        bindings = [
            FFmpegInputBinding(
                input_index=0,
                render_node_id="title_card_image",
                media_type=FFmpegInputMediaType.VIDEO,
                source_file=image_file,
                stream_label="0:v",
            ),
        ]

        arguments: list[str] = ["-y", "-loop", "1", "-t", f"{TOTAL_DURATION_SECONDS}"]

        arguments.extend(["-i", image_file])

        if music_file is not None:
            arguments.extend(["-i", music_file])

            bindings.append(
                FFmpegInputBinding(
                    input_index=1,
                    render_node_id="title_card_music",
                    media_type=FFmpegInputMediaType.AUDIO,
                    source_file=music_file,
                    stream_label="1:a",
                )
            )
        else:
            arguments.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{TOTAL_DURATION_SECONDS}",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                ]
            )

            bindings.append(
                FFmpegInputBinding(
                    input_index=1,
                    render_node_id="title_card_silence",
                    media_type=FFmpegInputMediaType.AUDIO,
                    source_file="anullsrc",
                    stream_label="1:a",
                )
            )

        input_plan = FFmpegInputPlan(
            bindings=bindings,
            input_count=len(bindings),
            video_input_count=1,
            audio_input_count=1,
        )

        arguments.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                f"[{video_output_label}]",
                "-map",
                f"[{audio_output_label}]",
                "-c:v",
                resolved_config.selected_video_codec,
                "-pix_fmt",
                pixel_format,
                "-c:a",
                resolved_config.selected_audio_codec,
                "-b:a",
                resolved_config.config.audio_bitrate,
                "-t",
                f"{TOTAL_DURATION_SECONDS}",
                staging_output_file,
            ]
        )

        command_plan = FFmpegCommandPlan(
            executable=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label=video_output_label,
            audio_output_label=audio_output_label,
            output_file=staging_output_file,
            arguments=arguments,
        )

        try:
            execution_result = self._execution_service.execute(
                command_plan,
                total_duration_seconds=int(TOTAL_DURATION_SECONDS),
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
                duration_seconds=int(TOTAL_DURATION_SECONDS),
                status=RenderStatus.COMPLETED,
                ffmpeg_command=ffmpeg_command,
                exit_code=execution_result.exit_code,
                selected_video_codec=resolved_config.selected_video_codec,
                selected_audio_codec=resolved_config.selected_audio_codec,
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
            duration_seconds=int(TOTAL_DURATION_SECONDS),
            status=RenderStatus.FAILED,
            error_message=error_message,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
            failure_category=classify_render_failure(failure_stage),
        )

    @classmethod
    def _build_filter_complex(
        cls,
        *,
        channel_name: str,
        title_text: str,
        text_style: TitleCardTextStyle,
        position: ThumbnailTextPosition,
        width: int,
        height: int,
        frame_rate: float,
        pixel_format: str,
        has_music: bool,
    ) -> tuple[str, str, str]:
        """Return (filter_complex, video_output_label, audio_output_label)."""

        x_expr, y_expr = cls._position_expressions(position)

        clauses: list[str] = [
            f"[0:v]scale={width}:{height},fps={cls._format_number(frame_rate)},"
            f"format={pixel_format},setpts=PTS-STARTPTS[titlecard_base]"
        ]

        font_file = VideoFilterTranslationService._resolve_subtitle_font_file()

        fontfile_clause = f":fontfile='{font_file}'" if font_file is not None else ""

        # Beat 1: "{channel_name}" (larger) stacked above "presents"
        # (smaller) - both share the same beat-1 timing window, both
        # anchored around the shared position point rather than each
        # independently positioned.
        channel_text_path = (
            "'"
            + VideoFilterTranslationService._write_subtitle_text_file(channel_name)
            + "'"
        )

        presents_text_path = (
            "'"
            + VideoFilterTranslationService._write_subtitle_text_file("presents")
            + "'"
        )

        beat_1_alpha = cls._fade_alpha_expression(
            start_seconds=_BEAT_1_START_SECONDS,
            end_seconds=_BEAT_1_END_SECONDS,
        )

        beat_1_enable = VideoFilterTranslationService._enable_expression(
            _BEAT_1_START_SECONDS, _BEAT_1_END_SECONDS
        )

        clauses.append(
            "[titlecard_base]drawtext="
            f"textfile={channel_text_path}:"
            f"fontsize={_BASE_CHANNEL_FONTSIZE}:"
            "fontcolor=white:"
            f"borderw={text_style.borderw}:bordercolor=black@0.7:"
            "box=1:boxcolor=black@0.55:boxborderw=16:"
            f"x={x_expr}:y=({y_expr})-(text_h+14):"
            f"alpha='{beat_1_alpha}':"
            f"enable={beat_1_enable}"
            f"{fontfile_clause}"
            "[titlecard_beat1a]"
        )

        clauses.append(
            "[titlecard_beat1a]drawtext="
            f"textfile={presents_text_path}:"
            f"fontsize={_BASE_PRESENTS_FONTSIZE}:"
            "fontcolor=white:"
            "borderw=2:bordercolor=black@0.7:"
            "box=1:boxcolor=black@0.55:boxborderw=12:"
            f"x={x_expr}:y=({y_expr})+(text_h*0.2):"
            f"alpha='{beat_1_alpha}':"
            f"enable={beat_1_enable}"
            f"{fontfile_clause}"
            "[titlecard_beat1b]"
        )

        # Beat 2: the title itself - the single most dominant element
        # of the whole card.
        title_text_path = (
            "'"
            + VideoFilterTranslationService._write_subtitle_text_file(title_text)
            + "'"
        )

        beat_2_alpha = cls._fade_alpha_expression(
            start_seconds=_BEAT_2_START_SECONDS,
            end_seconds=_BEAT_2_END_SECONDS,
            fade_out=False,
        )

        beat_2_enable = VideoFilterTranslationService._enable_expression(
            _BEAT_2_START_SECONDS, _BEAT_2_END_SECONDS
        )

        title_fontsize = round(_BASE_TITLE_FONTSIZE * text_style.fontsize_scale)

        clauses.append(
            "[titlecard_beat1b]drawtext="
            f"textfile={title_text_path}:"
            f"fontsize={title_fontsize}:"
            "fontcolor=white:"
            f"borderw={text_style.borderw}:bordercolor=black@0.8:"
            "box=1:boxcolor=black@0.55:boxborderw=28:"
            f"x={x_expr}:y={y_expr}:"
            f"alpha='{beat_2_alpha}':"
            f"enable={beat_2_enable}"
            f"{fontfile_clause}"
            "[titlecard_v]"
        )

        if has_music:
            clauses.append(
                "[1:a]atrim=0:"
                f"{TOTAL_DURATION_SECONDS},asetpts=PTS-STARTPTS,"
                f"apad=whole_dur={TOTAL_DURATION_SECONDS}[titlecard_a]"
            )
        else:
            clauses.append("[1:a]anull[titlecard_a]")

        return ";".join(clauses), "titlecard_v", "titlecard_a"

    @staticmethod
    def _position_expressions(position: ThumbnailTextPosition) -> tuple[str, str]:
        margin_x = f"(w*{_SAFE_MARGIN_FRACTION})"
        margin_y = f"(h*{_SAFE_MARGIN_FRACTION})"

        if position == ThumbnailTextPosition.TOP:
            return "(w-text_w)/2", margin_y

        if position == ThumbnailTextPosition.BOTTOM:
            return "(w-text_w)/2", f"(h-text_h-{margin_y})"

        if position == ThumbnailTextPosition.CENTER_LEFT:
            return margin_x, "(h-text_h)/2"

        if position == ThumbnailTextPosition.CENTER_RIGHT:
            return f"(w-text_w-{margin_x})", "(h-text_h)/2"

        return "(w-text_w)/2", "(h-text_h)/2"

    @staticmethod
    def _fade_alpha_expression(
        *,
        start_seconds: float,
        end_seconds: float,
        fade_out: bool = True,
    ) -> str:
        fade_in_end = start_seconds + _FADE_SECONDS

        if not fade_out:
            return f"if(lt(t,{fade_in_end}),(t-{start_seconds})/{_FADE_SECONDS},1)"

        fade_out_start = end_seconds - _FADE_SECONDS

        return (
            f"if(lt(t,{fade_in_end}),(t-{start_seconds})/{_FADE_SECONDS},"
            f"if(lt(t,{fade_out_start}),1,(({end_seconds}-t)/{_FADE_SECONDS})))"
        )

    @staticmethod
    def _format_number(value: float) -> str:
        if float(value).is_integer():
            return str(int(value))

        return f"{value:.3f}".rstrip("0").rstrip(".")
