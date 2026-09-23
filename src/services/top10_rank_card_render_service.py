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

# REQ-12 (top10 countdown rank cards), 2026-09-23: shorter and punchier
# than the title card's own 3.0s - this happens 10 times per video, so
# it needs to read fast without feeling like it's stalling the
# countdown's own "fast, energetic" pacing (genre.top10's own script
# profile). Extended per-card when a real voiceover line runs longer
# than this base duration - see build()'s own voiceover_duration_seconds
# parameter.
_BASE_DURATION_SECONDS = 1.5
_FADE_SECONDS = 0.25
_NUMBER_FONTSIZE = 220
_VOICEOVER_START_SECONDS = 0.3
_MINIMUM_TRAILING_SECONDS = 0.4

# Deliberately alert/energetic-friendly, not the same slow-burn dread
# corner as horror content might reach for - real per-rank variation
# is a small pan direction alternation (see _zoompan_expression), not
# a different zoom amount per card, so all 10 cards read as one
# consistent cinematic treatment rather than 10 independent choices.
_ZOOM_PER_SECOND = 0.02


class TopTenRankCardRenderService:
    """
    REQ-12: build one standalone, real short video+audio clip for a
    single countdown rank ("#10", "#9", ...) - a real animated number
    reveal over the countdown's one shared background image, a real
    "Number {N}." voiceover line mixed with the genre's own whoosh
    sting.

    Mirrors TitleCardRenderService's own proven shape exactly (hand-
    built FFmpegCommandPlan, direct FFmpegExecutionService.execute()
    call, reusing VideoFilterTranslationService's drawtext building
    blocks) - deliberately not built on RenderGraph/FilterGraph, for
    the same reason: no per-scene crossfade/timing concept applies to
    one static image held for a fixed duration.

    The SAME background image is passed in for every rank (by the
    caller, generated or manually supplied once per job) - this is
    the real, deliberate fix for cross-card visual consistency (see
    cinematic_touch_requirements' own REQ-12 design writeup): 10
    independently-generated backgrounds would risk visual drift, one
    shared image reused across all 10 cards cannot drift by
    construction. A small per-rank pan-direction alternation (not a
    per-rank background) keeps 10 consecutive cards from feeling
    static without ever risking that drift.
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
        rank: int,
        background_image_file: str,
        whoosh_sfx_file: str | None,
        voiceover_file: str | None,
        voiceover_duration_seconds: float | None,
        width: int,
        height: int,
        frame_rate: float,
        output_file: str,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Render one standalone rank-card clip.

        whoosh_sfx_file/voiceover_file are both optional - a card
        always has exactly one video and one audio stream either way
        (real silence when both are absent), matching every other
        standalone clip this codebase concatenates onto a render.
        """

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Rank card render output file cannot be empty.")

        if rank < 1 or rank > 10:
            raise ValueError(f"Rank card render requires rank 1-10, got {rank}.")

        target_output_file = Path(cleaned_output_file).as_posix()

        staging_output_file = ProductionRenderService._staging_output_file(
            target_output_file
        )

        resolved_config = self._capability_service.resolve()

        pixel_format = str(resolved_config.config.pixel_format.value)

        total_duration_seconds = self._total_duration_seconds(
            voiceover_duration_seconds
        )

        filter_complex, video_output_label, audio_output_label = (
            self._build_filter_complex(
                rank=rank,
                width=width,
                height=height,
                frame_rate=frame_rate,
                pixel_format=pixel_format,
                total_duration_seconds=total_duration_seconds,
                has_whoosh=whoosh_sfx_file is not None,
                has_voiceover=voiceover_file is not None,
            )
        )

        bindings = [
            FFmpegInputBinding(
                input_index=0,
                render_node_id="top10_rank_card_background",
                media_type=FFmpegInputMediaType.VIDEO,
                source_file=background_image_file,
                stream_label="0:v",
            ),
        ]

        arguments: list[str] = [
            "-y",
            "-loop",
            "1",
            "-t",
            f"{total_duration_seconds}",
            "-i",
            background_image_file,
        ]

        next_input_index = 1
        audio_inputs: list[str] = []

        if whoosh_sfx_file is not None:
            arguments.extend(["-i", whoosh_sfx_file])
            bindings.append(
                FFmpegInputBinding(
                    input_index=next_input_index,
                    render_node_id="top10_rank_card_whoosh",
                    media_type=FFmpegInputMediaType.AUDIO,
                    source_file=whoosh_sfx_file,
                    stream_label=f"{next_input_index}:a",
                )
            )
            audio_inputs.append(f"{next_input_index}:a")
            next_input_index += 1

        if voiceover_file is not None:
            arguments.extend(["-i", voiceover_file])
            bindings.append(
                FFmpegInputBinding(
                    input_index=next_input_index,
                    render_node_id="top10_rank_card_voiceover",
                    media_type=FFmpegInputMediaType.AUDIO,
                    source_file=voiceover_file,
                    stream_label=f"{next_input_index}:a",
                )
            )
            audio_inputs.append(f"{next_input_index}:a")
            next_input_index += 1

        if not audio_inputs:
            arguments.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{total_duration_seconds}",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                ]
            )
            bindings.append(
                FFmpegInputBinding(
                    input_index=next_input_index,
                    render_node_id="top10_rank_card_silence",
                    media_type=FFmpegInputMediaType.AUDIO,
                    source_file="anullsrc",
                    stream_label=f"{next_input_index}:a",
                )
            )

        input_plan = FFmpegInputPlan(
            bindings=bindings,
            input_count=len(bindings),
            video_input_count=1,
            # One real audio binding per whoosh/voiceover actually
            # supplied, plus the anullsrc fallback binding when
            # neither is - never a flat 1, since whoosh+voiceover
            # together are 2 real audio inputs (bug caught by real-
            # FFmpeg verification, not by the filter-graph logic
            # itself, which already handled 0/1/2 correctly).
            audio_input_count=len(bindings) - 1,
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
                f"{total_duration_seconds}",
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
                total_duration_seconds=int(total_duration_seconds) + 1,
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

    @staticmethod
    def _total_duration_seconds(voiceover_duration_seconds: float | None) -> float:
        if voiceover_duration_seconds is None:
            return _BASE_DURATION_SECONDS

        required = (
            _VOICEOVER_START_SECONDS
            + voiceover_duration_seconds
            + _MINIMUM_TRAILING_SECONDS
        )

        return max(_BASE_DURATION_SECONDS, required)

    @classmethod
    def _build_filter_complex(
        cls,
        *,
        rank: int,
        width: int,
        height: int,
        frame_rate: float,
        pixel_format: str,
        total_duration_seconds: float,
        has_whoosh: bool,
        has_voiceover: bool,
    ) -> tuple[str, str, str]:
        """Return (filter_complex, video_output_label, audio_output_label)."""

        total_frames = max(1, round(total_duration_seconds * frame_rate))

        # Alternate pan direction by rank parity - real, visible per-
        # card variation with zero risk of visual drift, since it's
        # the same shared image every time, just panned differently.
        pan_x_expr = (
            "iw/2-(iw/zoom/2)" if rank % 2 == 0 else "iw/2-(iw/zoom/2)+ (iw*0.01)"
        )

        clauses: list[str] = [
            f"[0:v]scale={width * 2}:{height * 2},"
            f"zoompan=z='min(zoom+{_ZOOM_PER_SECOND / frame_rate},1.15)':"
            f"x='{pan_x_expr}':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s={width}x{height}:fps={cls._format_number(frame_rate)},"
            f"format={pixel_format},setpts=PTS-STARTPTS[rankcard_base]"
        ]

        font_file = VideoFilterTranslationService._resolve_subtitle_font_file()

        fontfile_clause = f":fontfile='{font_file}'" if font_file is not None else ""

        number_text_path = (
            "'"
            + VideoFilterTranslationService._write_subtitle_text_file(str(rank))
            + "'"
        )

        alpha_expression = cls._fade_in_alpha_expression(total_duration_seconds)

        clauses.append(
            "[rankcard_base]drawtext="
            f"textfile={number_text_path}:"
            f"fontsize={_NUMBER_FONTSIZE}:"
            "fontcolor=white:"
            "borderw=8:bordercolor=black@0.85:"
            "box=1:boxcolor=black@0.4:boxborderw=32:"
            "x=(w-text_w)/2:y=(h-text_h)/2:"
            f"alpha='{alpha_expression}'"
            f"{fontfile_clause}"
            "[rankcard_v]"
        )

        audio_output_label = cls._build_audio_clauses(
            clauses,
            total_duration_seconds=total_duration_seconds,
            has_whoosh=has_whoosh,
            has_voiceover=has_voiceover,
        )

        return ";".join(clauses), "rankcard_v", audio_output_label

    @staticmethod
    def _build_audio_clauses(
        clauses: list[str],
        *,
        total_duration_seconds: float,
        has_whoosh: bool,
        has_voiceover: bool,
    ) -> str:
        whoosh_label = None
        voiceover_label = None
        next_input_index = 1

        if has_whoosh:
            whoosh_label = "rankcard_whoosh"
            clauses.append(
                f"[{next_input_index}:a]atrim=0:{total_duration_seconds},"
                f"asetpts=PTS-STARTPTS[{whoosh_label}]"
            )
            next_input_index += 1

        if has_voiceover:
            voiceover_label = "rankcard_voice"
            clauses.append(
                f"[{next_input_index}:a]"
                f"adelay={round(_VOICEOVER_START_SECONDS * 1000)}|"
                f"{round(_VOICEOVER_START_SECONDS * 1000)}[{voiceover_label}]"
            )
            next_input_index += 1

        if whoosh_label is not None and voiceover_label is not None:
            clauses.append(
                f"[{whoosh_label}][{voiceover_label}]amix=inputs=2:"
                f"duration=first,apad=whole_dur={total_duration_seconds}"
                "[rankcard_a]"
            )

            return "rankcard_a"

        if whoosh_label is not None:
            clauses.append(
                f"[{whoosh_label}]apad=whole_dur={total_duration_seconds}[rankcard_a]"
            )

            return "rankcard_a"

        if voiceover_label is not None:
            clauses.append(
                f"[{voiceover_label}]apad=whole_dur={total_duration_seconds}[rankcard_a]"
            )

            return "rankcard_a"

        clauses.append(f"[{next_input_index}:a]anull[rankcard_a]")

        return "rankcard_a"

    @staticmethod
    def _fade_in_alpha_expression(total_duration_seconds: float) -> str:
        fade_in_end = min(_FADE_SECONDS, total_duration_seconds)

        return f"if(lt(t,{fade_in_end}),t/{fade_in_end},1)"

    @staticmethod
    def _format_number(value: float) -> str:
        if float(value).is_integer():
            return str(int(value))

        return f"{value:.3f}".rstrip("0").rstrip(".")
