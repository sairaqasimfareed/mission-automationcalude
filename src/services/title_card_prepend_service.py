from __future__ import annotations

from pathlib import Path

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_input import FFmpegInputPlan
from src.models.render_failure_diagnosis import classify_render_failure
from src.models.render_result import RenderResult, RenderStatus
from src.services.fast_title_card_join import FastTitleCardJoin, Runner
from src.services.ffmpeg_capability_service import FFmpegCapabilityService
from src.services.ffmpeg_execution_service import (
    CancellationCheck,
    FFmpegExecutionService,
    ProgressCallback,
)
from src.services.join_segments_filter import JoinSegment, build_join_filter
from src.services.production_render_service import ProductionRenderService
from src.services.title_card_render_service import TOTAL_DURATION_SECONDS
from src.shared.logger import logger


class TitleCardPrependService:
    """
    REQ-4 (opening title card): join the standalone title-card clip
    (TitleCardRenderService's own output) onto the front of an
    already-finished render, producing one final file.

    Reuses ProductionRenderService._concat_chunks()'s own proven
    real-world finding rather than a second implementation: the concat
    DEMUXER (stream-copy, `-c copy`) requires byte-identical streams
    across segments and silently truncates audio when two
    independently-produced files don't match closely enough (confirmed
    on a real render there) - the concat FILTER instead genuinely re-
    decodes and re-encodes both segments into one continuous, correct
    stream, tolerant of any real encoder-state difference between the
    title card's own encode and the main render's own encode.
    """

    def __init__(
        self,
        *,
        capability_service: FFmpegCapabilityService | None = None,
        execution_service: FFmpegExecutionService | None = None,
        fast_join_enabled: bool = True,
        fast_join_runner: Runner | None = None,
    ) -> None:
        self._capability_service = capability_service or FFmpegCapabilityService()
        # The fast join (re-encode only the card, join with a stream copy, verify) is
        # tried first; anything it cannot do or verify falls back to the full
        # re-encode below. Off for callers that must always take the full path.
        self._fast_join_enabled = fast_join_enabled
        self._fast_join_runner = fast_join_runner

        self._execution_service = execution_service or FFmpegExecutionService()

    def prepend(
        self,
        *,
        title_card_file: str,
        main_video_file: str,
        output_file: str,
        main_video_duration_seconds: float,
        title_card_duration_seconds: float | None = None,
        title_card_has_audio: bool = True,
        fit_title_card_to: tuple[int, int] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Produce one final file: title_card_file's own real content,
        immediately followed by main_video_file's own real content.

        By default title_card_file is TitleCardRenderService's own
        output, built to match the main video exactly, so the segments
        are concatenated as-is. An operator-uploaded clip can be any
        size, frame rate or audio layout: passing fit_title_card_to
        (the main video's width, height) letterboxes it into that frame
        and normalises both segments' frame rate and audio format
        first; title_card_duration_seconds/title_card_has_audio then
        describe that clip (a silent clip gets matching silence).
        """

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Title card prepend output file cannot be empty.")

        target_output_file = Path(cleaned_output_file).as_posix()

        staging_output_file = ProductionRenderService._staging_output_file(
            target_output_file
        )

        resolved_config = self._capability_service.resolve()

        config = resolved_config.config

        if self._fast_join_enabled:
            fast = FastTitleCardJoin(
                ffmpeg_path=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
                ffprobe_path=resolved_config.capabilities.ffprobe_path or "ffprobe",
                preset=config.preset,
                crf=config.crf,
                pixel_format=str(config.pixel_format.value),
                audio_bitrate=config.audio_bitrate,
                extra_video_args=list(config.extra_video_args),
                extra_audio_args=list(config.extra_audio_args),
                runner=self._fast_join_runner,
            )
            outcome = fast.try_join(
                title_card_file=Path(title_card_file).resolve().as_posix(),
                main_video_file=Path(main_video_file).resolve().as_posix(),
                output_file=staging_output_file,
                title_card_has_audio=title_card_has_audio,
                cancellation_check=cancellation_check,
            )

            if outcome.joined:
                promoted_output_file = ProductionRenderService._promote_staged_output(
                    staging_output_file=staging_output_file,
                    target_output_file=target_output_file,
                )

                return RenderResult(
                    success=True,
                    output_file=promoted_output_file,
                    render_engine="ffmpeg",
                    render_time_seconds=outcome.elapsed_seconds,
                    duration_seconds=int(outcome.duration_seconds or 0),
                    status=RenderStatus.COMPLETED,
                    ffmpeg_command=outcome.command,
                    exit_code=0,
                    selected_video_codec=resolved_config.selected_video_codec,
                    selected_audio_codec=resolved_config.selected_audio_codec,
                )

            logger.info(
                "Fast title card join not used (%s); re-encoding the whole video.",
                outcome.reason,
            )

        segment_files = [title_card_file, main_video_file]

        arguments: list[str] = ["-y"]

        for segment_file in segment_files:
            arguments.extend(["-i", Path(segment_file).resolve().as_posix()])

        title_card_seconds = (
            title_card_duration_seconds
            if title_card_duration_seconds is not None
            else TOTAL_DURATION_SECONDS
        )

        if fit_title_card_to is not None:
            join_clauses, joined_video, joined_audio = build_join_filter(
                [
                    JoinSegment(
                        video_label="0:v:0",
                        audio_label="0:a:0" if title_card_has_audio else None,
                        duration_seconds=title_card_seconds,
                        fit_to_frame=True,
                    ),
                    JoinSegment(
                        video_label="1:v:0",
                        audio_label="1:a:0",
                        duration_seconds=main_video_duration_seconds,
                    ),
                ],
                width=fit_title_card_to[0],
                height=fit_title_card_to[1],
            )
            filter_complex = ";".join(join_clauses)
            concat_video_label = joined_video
            concat_audio_label = joined_audio
        else:
            concat_stream_labels = "".join(
                f"[{index}:v:0][{index}:a:0]" for index in range(len(segment_files))
            )

            filter_complex = (
                f"{concat_stream_labels}concat="
                f"n={len(segment_files)}:v=1:a=1[concat_v][concat_a]"
            )
            concat_video_label = "concat_v"
            concat_audio_label = "concat_a"

        arguments.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                f"[{concat_video_label}]",
                "-map",
                f"[{concat_audio_label}]",
                "-c:v",
                resolved_config.selected_video_codec,
            ]
        )

        if resolved_config.selected_video_codec in {"libx264", "libx265"}:
            arguments.extend(["-preset", config.preset, "-crf", str(config.crf)])

        arguments.extend(["-pix_fmt", str(config.pixel_format.value)])

        arguments.extend(config.extra_video_args)

        arguments.extend(
            ["-c:a", resolved_config.selected_audio_codec, "-b:a", config.audio_bitrate]
        )

        arguments.extend(config.extra_audio_args)

        arguments.append(staging_output_file)

        command_plan = FFmpegCommandPlan(
            executable=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
            input_plan=FFmpegInputPlan(),
            filter_complex=filter_complex,
            video_output_label=concat_video_label,
            audio_output_label=concat_audio_label,
            output_file=staging_output_file,
            arguments=arguments,
        )

        total_duration_seconds = title_card_seconds + main_video_duration_seconds

        try:
            execution_result = self._execution_service.execute(
                command_plan,
                total_duration_seconds=total_duration_seconds,
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
                duration_seconds=int(total_duration_seconds),
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
            duration_seconds=int(total_duration_seconds),
            status=RenderStatus.FAILED,
            error_message=error_message,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
            failure_category=classify_render_failure(failure_stage),
        )
