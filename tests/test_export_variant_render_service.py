from __future__ import annotations

from pathlib import Path

import pytest

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.render_result import RenderResult
from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob
from src.services.export_variant_render_service import ExportVariantRenderService


class _FakeCapabilityService:
    def resolve(self, config: FFmpegConfig | None = None) -> FFmpegResolvedConfig:
        return FFmpegResolvedConfig(
            config=config or FFmpegConfig(),
            capabilities=FFmpegCapabilities(
                ffmpeg_available=True,
                ffprobe_available=True,
                ffmpeg_path="ffmpeg",
                ffprobe_path="ffprobe",
                encoders={"libx264", "aac"},
            ),
            selected_video_codec="libx264",
            selected_audio_codec="aac",
        )


class _FakeExecutionService:
    def __init__(self) -> None:
        self.calls: list[tuple[FFmpegCommandPlan, float]] = []

    def execute(
        self,
        command_plan: FFmpegCommandPlan,
        *,
        total_duration_seconds: float,
        **_kwargs: object,
    ) -> None:
        self.calls.append((command_plan, total_duration_seconds))


def _job(*, output_resolution: str = "1920x1080") -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
        output_resolution=output_resolution,
    )


def _render_result(
    *,
    output_file: str | None = "F:/renders/job1/output.mp4",
    duration_seconds: int = 60,
) -> RenderResult:
    return RenderResult(
        success=True,
        output_file=output_file,
        render_engine="ffmpeg",
        duration_seconds=duration_seconds,
    )


def _service() -> tuple[ExportVariantRenderService, _FakeExecutionService]:
    execution = _FakeExecutionService()
    service = ExportVariantRenderService(
        capability_service=_FakeCapabilityService(),  # type: ignore[arg-type]
        execution_service=execution,  # type: ignore[arg-type]
    )

    return service, execution


def test_landscape_variant_is_a_passthrough_with_no_ffmpeg_call() -> None:
    """
    Real-world finding: every base render this app produces is already
    landscape (the output-resolution picker only ever offers 16:9
    presets) - a landscape variant is a genuine no-op, so it must
    point directly at the existing render output rather than spending
    a real FFmpeg pass producing a needless duplicate file.
    """

    service, execution = _service()
    render_result = _render_result(output_file="F:/renders/job1/output.mp4")

    variant = service.build(
        job=_job(),
        render_result=render_result,
        orientation=AspectRatio.LANDSCAPE,
    )

    assert variant.orientation == AspectRatio.LANDSCAPE
    assert variant.output_file == "F:/renders/job1/output.mp4"
    assert execution.calls == []


def test_portrait_variant_builds_a_pad_and_blur_filter_complex() -> None:
    service, execution = _service()
    render_result = _render_result(
        output_file="F:/renders/job1/output.mp4", duration_seconds=42
    )

    variant = service.build(
        job=_job(output_resolution="1920x1080"),
        render_result=render_result,
        orientation=AspectRatio.PORTRAIT,
    )

    expected_output = str(Path("F:/renders/job1/output_portrait.mp4"))
    assert variant.orientation == AspectRatio.PORTRAIT
    assert variant.output_file == expected_output

    assert len(execution.calls) == 1
    command_plan, total_duration_seconds = execution.calls[0]

    assert total_duration_seconds == 42.0
    assert command_plan.output_file == expected_output
    # Target canvas is the source resolution's tier, swapped (portrait).
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in (
        command_plan.filter_complex
    )
    assert "crop=1080:1920" in command_plan.filter_complex
    assert "gblur=sigma=" in command_plan.filter_complex
    assert "scale=1080:-2" in command_plan.filter_complex
    assert "overlay=(W-w)/2:(H-h)/2" in command_plan.filter_complex
    # Never distorts - no bare "scale=1080:1920" without
    # force_original_aspect_ratio anywhere driving the foreground.
    assert "-map" in command_plan.arguments
    assert "[outv]" in command_plan.arguments
    assert "0:a" in command_plan.arguments
    assert "-c:a" in command_plan.arguments
    assert "copy" in command_plan.arguments


def test_portrait_variant_reuses_the_resolved_encoder_settings() -> None:
    service, execution = _service()

    service.build(
        job=_job(output_resolution="1280x720"),
        render_result=_render_result(),
        orientation=AspectRatio.PORTRAIT,
    )

    command_plan, _ = execution.calls[0]

    assert "-c:v" in command_plan.arguments
    assert "libx264" in command_plan.arguments
    assert "-crf" in command_plan.arguments
    assert "-preset" in command_plan.arguments


def test_build_requires_a_render_result_with_an_output_file() -> None:
    service, _ = _service()

    with pytest.raises(ValueError, match="real output file"):
        service.build(
            job=_job(),
            render_result=_render_result(output_file=None),
            orientation=AspectRatio.LANDSCAPE,
        )
