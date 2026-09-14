from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from src.models.enums import Platform
from src.models.export_variant import ExportVariant
from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_input import (
    FFmpegInputBinding,
    FFmpegInputMediaType,
    FFmpegInputPlan,
)
from src.models.render_result import RenderResult
from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob
from src.services.ffmpeg_capability_service import FFmpegCapabilityService
from src.services.ffmpeg_execution_service import FFmpegExecutionService

# The background-blur-fill sigma - high enough that the padded frame
# reads as an intentional soft backdrop, not a compression artifact.
_BACKGROUND_BLUR_SIGMA = 20

# Discussed and locked in: a short, dedicated end-card, not baked into
# the main content - long enough to read comfortably, short enough not
# to cause drop-off right at the end.
_END_CARD_DURATION_SECONDS = 5.0

# Skip the opening hook - the highest-retention-risk moment in the
# whole video - before the persistent watermark appears at all.
_WATERMARK_DELAY_SECONDS = 4.0

# Short, persistent watermark text - kept to just the verb (no channel
# name) so it stays small and unobtrusive across the whole runtime.
# The full "<verb> <channel>" sentence is reserved for the dedicated
# end-card moment, not repeated throughout.
_WATERMARK_TEXT: dict[Platform, str] = {
    Platform.YOUTUBE: "Subscribe",
    Platform.FACEBOOK: "Follow",
    Platform.TIKTOK: "Follow",
}

# Facebook and TikTok share the "Follow" verb but are deliberately two
# separate table entries, not a shared fallback - Facebook's wording
# can diverge later without disturbing TikTok's.
_END_CARD_TEXT: dict[Platform, str] = {
    Platform.YOUTUBE: "Subscribe to {channel_name}",
    Platform.FACEBOOK: "Follow {channel_name}",
    Platform.TIKTOK: "Follow {channel_name}",
}

# Real-world finding, 2026-09-13 (video_filter_translation_service.py's
# own subtitle drawtext path): Windows FFmpeg builds commonly ship
# without fontconfig support, and even fontconfig-enabled builds fail
# without a configured fonts.conf - drawtext must never rely on
# FFmpeg's own font=<name> resolution. Copied here rather than
# imported - that service's own methods are shaped for per-scene
# RenderNodes, not a standalone pass (see this class's own docstring),
# but the proven font-fallback/text-escaping approach is exactly right
# to reuse.
_WINDOWS_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)
_LINUX_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
_MACOS_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

_EXPORT_TEXT_CACHE_DIRECTORY = Path("data/export_variant_text_cache")


class ExportVariantRenderService:
    """
    Post-Script-Approval Production Plan, post-render export variants:
    produce one orientation-reformatted, platform-branded copy of a
    job's already fully-rendered video - a lightweight second FFmpeg
    pass over the EXISTING output file, never a re-render of the
    timeline itself.

    Orientation and platform are two independent choices, each driving
    only the downstream pieces it actually determines (see the design
    table in this initiative's own plan): orientation drives the
    frame-level reformat AND the watermark's corner (bottom-right for
    landscape, bottom-left for portrait, to stay clear of TikTok/
    Reels/Shorts' own right-edge UI column - a property of the
    portrait short-form layout, not of any one platform's brand);
    platform drives the watermark/end-card TEXT and, from a later
    phase, SEO/thumbnail packaging. platform=None means no watermark
    and no end-card at all - a plain, optionally reformatted export.

    Deliberately does NOT go through FilterGraphBuilderService/
    FFmpegCommandBuilderService (both tightly coupled to a full
    RenderGraph describing every scene) - FFmpegCommandPlan/
    FFmpegInputPlan/FFmpegInputBinding validate independently of that
    graph, so a single-input, single-output command plan can be
    hand-built directly and handed to the same, fully generic
    FFmpegExecutionService.execute() the base render already uses.
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
        job: VideoJob,
        render_result: RenderResult,
        orientation: AspectRatio,
        platform: Platform | None = None,
    ) -> ExportVariant:
        """
        Build one export variant.

        Real-world finding this session: every base render this app
        produces is landscape today (VideoJob.output_resolution's own
        picker only ever offers 16:9 presets) - a landscape request
        with no platform chosen is therefore a genuine no-op (nothing
        to reformat, nothing to brand), so it's returned pointing
        directly at the existing render output rather than running
        FFmpeg to produce a needless duplicate file. Any other
        combination (portrait reformat, and/or a real platform) runs
        the real FFmpeg pass.
        """

        if render_result.output_file is None:
            raise ValueError(
                "Export variant generation requires a render result "
                "with a real output file."
            )

        source_file = render_result.output_file

        if orientation == AspectRatio.LANDSCAPE and platform is None:
            return ExportVariant(orientation=orientation, output_file=source_file)

        return self._build_processed_variant(
            job=job,
            source_file=source_file,
            orientation=orientation,
            platform=platform,
            duration_seconds=render_result.duration_seconds,
        )

    def _build_processed_variant(
        self,
        *,
        job: VideoJob,
        source_file: str,
        orientation: AspectRatio,
        platform: Platform | None,
        duration_seconds: int,
    ) -> ExportVariant:
        resolved_config = self._capability_service.resolve()
        source_width, source_height = self._parse_resolution(job.output_resolution)

        # Swap the same resolution tier the user already chose for the
        # base render (e.g. 1920x1080 -> 1080x1920) rather than
        # introducing a separate portrait-resolution picker.
        target_width, target_height = (
            (source_height, source_width)
            if orientation == AspectRatio.PORTRAIT
            else (source_width, source_height)
        )

        clauses: list[str] = []
        video_label = "0:v"

        if orientation == AspectRatio.PORTRAIT:
            clause, video_label = self._reformat_clause(
                input_label=video_label,
                width=target_width,
                height=target_height,
            )
            clauses.append(clause)

        content_duration = float(max(1, duration_seconds))
        total_duration = content_duration
        audio_label = "0:a"

        if platform is not None:
            # Real-world finding, 2026-09-14: confirmed live via an
            # extracted end-card frame - tpad freezes the actual LAST
            # rendered frame, and that frame's own timestamp still
            # fell inside a naive between(t, delay, content_duration)
            # window (frame timing is discrete; the frame right at the
            # boundary still qualifies), so the watermark was already
            # burned into the exact pixels that then got frozen and
            # cloned into the end-card - visibly stacking the small
            # watermark on top of the big end-card text, the one thing
            # this design explicitly rules out. A real margin before
            # the true content end guarantees the frame that actually
            # gets frozen is clean.
            watermark_end_seconds = max(
                _WATERMARK_DELAY_SECONDS, content_duration - 1.0
            )
            watermark_clause, video_label = self._watermark_clause(
                input_label=video_label,
                platform=platform,
                orientation=orientation,
                start_seconds=_WATERMARK_DELAY_SECONDS,
                end_seconds=watermark_end_seconds,
            )
            clauses.append(watermark_clause)

            end_card_clause, video_label = self._end_card_clause(
                input_label=video_label,
                platform=platform,
                channel_name=job.channel_name,
                content_end_seconds=content_duration,
            )
            clauses.append(end_card_clause)

            audio_clause, audio_label = self._audio_pad_clause()
            clauses.append(audio_clause)

            total_duration = content_duration + _END_CARD_DURATION_SECONDS

        output_file = self._output_file_path(
            source_file, orientation=orientation, platform=platform
        )

        filter_complex = ";".join(clauses)

        input_binding = FFmpegInputBinding(
            input_index=0,
            render_node_id="export_variant_source",
            media_type=FFmpegInputMediaType.VIDEO,
            source_file=source_file,
            stream_label="0:v",
        )
        input_plan = FFmpegInputPlan(
            bindings=[input_binding],
            input_count=1,
            video_input_count=1,
            audio_input_count=0,
        )

        video_map = video_label if video_label == "0:v" else f"[{video_label}]"
        audio_map = audio_label if audio_label == "0:a" else f"[{audio_label}]"

        arguments = [
            "-y",
            "-i",
            source_file,
            "-filter_complex",
            filter_complex,
            "-map",
            video_map,
            "-map",
            audio_map,
            "-c:v",
            resolved_config.selected_video_codec,
        ]

        # Real-world finding, 2026-09-14: confirmed live against this
        # machine's own real hardware encoder (h264_nvenc, auto-
        # selected because it has an NVIDIA GPU) - -crf/-preset are
        # libx264/libx265-specific flags; NVENC rejects them outright
        # (a real ffmpeg failure, not a hypothetical one). Matches
        # FFmpegCommandBuilderService's own existing guard exactly
        # (the base render already has this right) rather than
        # inventing a different rule here.
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

        if platform is None:
            # No audio processing needed - a lossless passthrough copy.
            arguments.extend(["-c:a", "copy"])
        else:
            # apad requires a real re-encode - a stream copy cannot
            # extend an already-finalized audio stream.
            arguments.extend(
                [
                    "-c:a",
                    resolved_config.selected_audio_codec,
                    "-b:a",
                    resolved_config.config.audio_bitrate,
                ]
            )

        arguments.append(output_file)

        command_plan = FFmpegCommandPlan(
            executable=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label=(
                video_label if video_label != "0:v" else "source_video"
            ),
            audio_output_label=(
                audio_label if audio_label != "0:a" else "source_audio"
            ),
            output_file=output_file,
            arguments=arguments,
        )

        self._execution_service.execute(
            command_plan,
            total_duration_seconds=total_duration,
        )

        return ExportVariant(
            orientation=orientation,
            platform=platform,
            output_file=output_file,
        )

    @staticmethod
    def _output_file_path(
        source_file: str,
        *,
        orientation: AspectRatio,
        platform: Platform | None,
    ) -> str:
        suffix_parts = []

        if orientation == AspectRatio.PORTRAIT:
            suffix_parts.append("portrait")

        if platform is not None:
            suffix_parts.append(platform.value)

        suffix = ("_" + "_".join(suffix_parts)) if suffix_parts else ""
        source_path = Path(source_file)

        return str(
            source_path.with_name(f"{source_path.stem}{suffix}{source_path.suffix}")
        )

    @staticmethod
    def _reformat_clause(
        *, input_label: str, width: int, height: int
    ) -> tuple[str, str]:
        output_label = "reformatted"
        clause = (
            f"[{input_label}]split=2[bg][fg];"
            f"[bg]scale={width}:{height}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"gblur=sigma={_BACKGROUND_BLUR_SIGMA}[bgv];"
            f"[fg]scale={width}:-2[fgv];"
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2:format=auto[{output_label}]"
        )

        return clause, output_label

    @classmethod
    def _watermark_clause(
        cls,
        *,
        input_label: str,
        platform: Platform,
        orientation: AspectRatio,
        start_seconds: float,
        end_seconds: float,
    ) -> tuple[str, str]:
        text_file = cls._write_export_text_file(_WATERMARK_TEXT[platform])
        x_expr, y_expr = cls._watermark_position(orientation)

        options = {
            "textfile": f"'{text_file}'",
            "fontcolor": "white@0.85",
            "fontsize": "36",
            "box": "1",
            "boxcolor": "black@0.4",
            "boxborderw": "12",
            "x": x_expr,
            "y": y_expr,
            "enable": f"'between(t,{cls._number(start_seconds)},{cls._number(end_seconds)})'",
        }

        font_file = cls._resolve_font_file()

        if font_file is not None:
            options["fontfile"] = f"'{font_file}'"

        output_label = "watermarked"
        options_text = ":".join(f"{key}={value}" for key, value in options.items())
        clause = f"[{input_label}]drawtext={options_text}[{output_label}]"

        return clause, output_label

    @staticmethod
    def _watermark_position(orientation: AspectRatio) -> tuple[str, str]:
        # Orientation-driven, not platform-driven - see this class's
        # own docstring for why (TikTok/Reels/Shorts' shared right-edge
        # UI column is a property of the portrait layout itself).
        x_expr = "30" if orientation == AspectRatio.PORTRAIT else "w-text_w-30"

        return x_expr, "h-text_h-30"

    @classmethod
    def _end_card_clause(
        cls,
        *,
        input_label: str,
        platform: Platform,
        channel_name: str,
        content_end_seconds: float,
    ) -> tuple[str, str]:
        padded_label = "padded"
        tpad_clause = (
            f"[{input_label}]tpad=stop_mode=clone:"
            f"stop_duration={cls._number(_END_CARD_DURATION_SECONDS)}[{padded_label}]"
        )

        text = _END_CARD_TEXT[platform].format(channel_name=channel_name)
        text_file = cls._write_export_text_file(text)
        end_seconds_text = cls._number(content_end_seconds)

        options = {
            "textfile": f"'{text_file}'",
            "fontcolor": "white",
            "fontsize": "64",
            "box": "1",
            "boxcolor": "black@0.6",
            "boxborderw": "24",
            "x": "(w-text_w)/2",
            "y": "(h-text_h)/2",
            "enable": f"'gte(t,{end_seconds_text})'",
            # A quick half-second fade-in for the end-card text itself
            # (the frozen frame underneath has no cut to fade from -
            # it's the same last frame continuing).
            "alpha": (
                f"'if(lt(t,{end_seconds_text}+0.5)," f"(t-{end_seconds_text})/0.5,1)'"
            ),
        }

        font_file = cls._resolve_font_file()

        if font_file is not None:
            options["fontfile"] = f"'{font_file}'"

        output_label = "endcard"
        options_text = ":".join(f"{key}={value}" for key, value in options.items())
        text_clause = f"[{padded_label}]drawtext={options_text}[{output_label}]"

        return f"{tpad_clause};{text_clause}", output_label

    @staticmethod
    def _audio_pad_clause() -> tuple[str, str]:
        output_label = "outa"
        clause = (
            f"[0:a]apad=pad_dur={ExportVariantRenderService._number(_END_CARD_DURATION_SECONDS)}"
            f"[{output_label}]"
        )

        return clause, output_label

    @staticmethod
    def _number(value: float) -> str:
        return f"{value:g}"

    @classmethod
    def _write_export_text_file(cls, text: str) -> str:
        """
        Write drawtext content to a real file and return its FFmpeg-
        safe escaped path, exactly matching
        video_filter_translation_service.py's own textfile= approach -
        real-world finding, 2026-09-13: inline text= requires escaping
        every FFmpeg-special character (quotes, colons, percent signs,
        brackets) inside an already-quoted filtergraph value, and a
        real narration line there once corrupted that escaping and
        leaked raw filter syntax onto screen. textfile= sidesteps the
        whole class of inline-escaping bugs - only the file PATH needs
        escaping, never the text content.
        """

        _EXPORT_TEXT_CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        file_path = _EXPORT_TEXT_CACHE_DIRECTORY / f"{digest}.txt"

        if not file_path.exists():
            file_path.write_text(text, encoding="utf-8")

        return cls._escape_drawtext_path(file_path.as_posix())

    @staticmethod
    def _escape_drawtext_path(path: str) -> str:
        return path.replace("\\", "\\\\").replace("'", r"'\''").replace(":", r"\:")

    @classmethod
    def _resolve_font_file(cls) -> str | None:
        if sys.platform.startswith("win"):
            candidates = _WINDOWS_FONT_CANDIDATES
        elif sys.platform == "darwin":
            candidates = _MACOS_FONT_CANDIDATES
        else:
            candidates = _LINUX_FONT_CANDIDATES

        for candidate in candidates:
            if Path(candidate).exists():
                return candidate.replace("\\", "/").replace(":", r"\:")

        return None

    @staticmethod
    def _parse_resolution(resolution: str) -> tuple[int, int]:
        try:
            width_text, height_text = resolution.lower().split("x", 1)

            return int(width_text), int(height_text)
        except (ValueError, AttributeError) as error:
            raise ValueError(
                f"Cannot parse output resolution '{resolution}' - "
                "expected WIDTHxHEIGHT."
            ) from error
