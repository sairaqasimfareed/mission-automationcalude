from __future__ import annotations

from pathlib import Path

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


class ExportVariantRenderService:
    """
    Post-Script-Approval Production Plan, post-render export variants:
    produce one orientation-reformatted (and, from a later phase,
    watermark/CTA-branded, platform-packaged) copy of a job's already
    fully-rendered video - a lightweight second FFmpeg pass over the
    EXISTING output file, never a re-render of the timeline itself.

    Orientation and platform are two independent choices, each driving
    only the downstream pieces it actually determines - this class
    owns the orientation-driven frame-level reformat (this phase) and,
    from Phase 2 on, the platform-driven watermark/end-card overlay.
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
    ) -> ExportVariant:
        """
        Build one orientation-only export variant (platform=None -
        later phases attach watermark/end-card/SEO once a real
        platform is chosen).

        Real-world finding this session: every base render this app
        produces is landscape today (VideoJob.output_resolution's own
        picker only ever offers 16:9 presets) - a landscape variant is
        therefore always a genuine no-op (the source already IS that
        shape), so it's returned pointing directly at the existing
        render output rather than running FFmpeg to produce a
        needless duplicate file.
        """

        if render_result.output_file is None:
            raise ValueError(
                "Export variant generation requires a render result "
                "with a real output file."
            )

        source_file = render_result.output_file

        if orientation == AspectRatio.LANDSCAPE:
            return ExportVariant(orientation=orientation, output_file=source_file)

        return self._build_portrait_variant(
            job=job,
            source_file=source_file,
            duration_seconds=render_result.duration_seconds,
        )

    def _build_portrait_variant(
        self,
        *,
        job: VideoJob,
        source_file: str,
        duration_seconds: int,
    ) -> ExportVariant:
        source_width, source_height = self._parse_resolution(job.output_resolution)

        # Swap the same resolution tier the user already chose for the
        # base render (e.g. 1920x1080 -> 1080x1920) rather than
        # introducing a separate portrait-resolution picker - keeps
        # the pixel budget consistent with what they already picked.
        target_width, target_height = source_height, source_width

        output_file = str(
            Path(source_file).with_name(
                f"{Path(source_file).stem}_portrait{Path(source_file).suffix}"
            )
        )

        filter_complex = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={target_width}:{target_height}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={target_width}:{target_height},"
            f"gblur=sigma={_BACKGROUND_BLUR_SIGMA}[bgv];"
            f"[fg]scale={target_width}:-2[fgv];"
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2:format=auto[outv]"
        )

        resolved_config = self._capability_service.resolve()

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

        arguments = [
            "-y",
            "-i",
            source_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "0:a",
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

        arguments.extend(
            [
                "-pix_fmt",
                resolved_config.config.pixel_format.value,
                "-c:a",
                "copy",
                output_file,
            ]
        )

        command_plan = FFmpegCommandPlan(
            executable=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label="outv",
            audio_output_label="0:a",
            output_file=output_file,
            arguments=arguments,
        )

        self._execution_service.execute(
            command_plan,
            total_duration_seconds=float(max(1, duration_seconds)),
        )

        return ExportVariant(
            orientation=AspectRatio.PORTRAIT,
            output_file=output_file,
        )

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
