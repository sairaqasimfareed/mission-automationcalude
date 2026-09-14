from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.models.enums import Platform
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
    assert "[reformatted]" in command_plan.arguments
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


def test_landscape_with_a_platform_is_no_longer_a_passthrough() -> None:
    """
    Phase 1's "landscape is always a no-op" only held while platform
    was always None - a landscape export with a real platform chosen
    still needs the watermark/end-card FFmpeg pass, even though the
    frame itself needs no reformatting.
    """

    service, execution = _service()

    variant = service.build(
        job=_job(),
        render_result=_render_result(output_file="F:/renders/job1/output.mp4"),
        orientation=AspectRatio.LANDSCAPE,
        platform=Platform.YOUTUBE,
    )

    assert len(execution.calls) == 1
    assert variant.platform == Platform.YOUTUBE
    assert variant.output_file != "F:/renders/job1/output.mp4"
    assert "youtube" in variant.output_file


def test_platform_none_is_still_a_passthrough_for_landscape() -> None:
    service, execution = _service()

    variant = service.build(
        job=_job(),
        render_result=_render_result(output_file="F:/renders/job1/output.mp4"),
        orientation=AspectRatio.LANDSCAPE,
        platform=None,
    )

    assert execution.calls == []
    assert variant.output_file == "F:/renders/job1/output.mp4"


def test_watermark_is_positioned_bottom_right_for_landscape() -> None:
    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(),
        orientation=AspectRatio.LANDSCAPE,
        platform=Platform.YOUTUBE,
    )

    command_plan, _ = execution.calls[0]
    assert "x=w-text_w-30" in command_plan.filter_complex
    assert "x=30:" not in command_plan.filter_complex


def test_watermark_is_positioned_bottom_left_for_portrait() -> None:
    """
    Orientation-driven, not platform-driven - stays clear of TikTok/
    Reels/Shorts' own right-edge UI column regardless of which
    platform this export is actually for.
    """

    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(),
        orientation=AspectRatio.PORTRAIT,
        platform=Platform.FACEBOOK,
    )

    command_plan, _ = execution.calls[0]
    assert "x=30:" in command_plan.filter_complex
    assert "x=w-text_w-30" not in command_plan.filter_complex


def _textfile_contents(filter_complex: str) -> list[str]:
    """
    Extract and read back the real text written by
    _write_export_text_file() for every textfile= reference in a
    filter_complex string - drawtext's own textfile= technique exists
    specifically so text content never has to survive filtergraph
    escaping, so a test that only checked the escaped PATH string
    could never actually catch a wrong word ending up in the file.
    """

    contents = []

    for match in re.finditer(r"textfile='([^']+)'", filter_complex):
        escaped_path = match.group(1)
        real_path = escaped_path.replace(r"\:", ":").replace(r"'\''", "'")
        contents.append(Path(real_path).read_text(encoding="utf-8"))

    return contents


def test_watermark_text_is_the_platform_specific_verb() -> None:
    for platform, expected_text in (
        (Platform.YOUTUBE, "Subscribe"),
        (Platform.FACEBOOK, "Follow"),
        (Platform.TIKTOK, "Follow"),
    ):
        service, execution = _service()

        service.build(
            job=_job(),
            render_result=_render_result(),
            orientation=AspectRatio.LANDSCAPE,
            platform=platform,
        )

        command_plan, _ = execution.calls[0]
        texts = _textfile_contents(command_plan.filter_complex)
        assert texts[0] == expected_text


def test_end_card_wording_differs_by_platform() -> None:
    for platform, expected_text in (
        (Platform.YOUTUBE, "Subscribe to Test Channel"),
        (Platform.FACEBOOK, "Follow Test Channel"),
        (Platform.TIKTOK, "Follow Test Channel"),
    ):
        service, execution = _service()

        service.build(
            job=_job(),
            render_result=_render_result(),
            orientation=AspectRatio.LANDSCAPE,
            platform=platform,
        )

        command_plan, _ = execution.calls[0]
        texts = _textfile_contents(command_plan.filter_complex)
        # [0] is the watermark's short verb, [1] is the end card's
        # full sentence - see test_watermark_text_is_the_platform_specific_verb
        # for the watermark half of this same pair.
        assert texts[1] == expected_text


def test_end_card_freezes_the_last_frame_and_extends_total_duration() -> None:
    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(duration_seconds=60),
        orientation=AspectRatio.LANDSCAPE,
        platform=Platform.YOUTUBE,
    )

    command_plan, total_duration_seconds = execution.calls[0]
    assert "tpad=stop_mode=clone:stop_duration=5" in command_plan.filter_complex
    assert total_duration_seconds == 65.0


def test_watermark_stops_before_the_frame_that_gets_frozen() -> None:
    """
    Real-world finding, 2026-09-14: confirmed live via an extracted
    end-card frame - tpad freezes the actual LAST rendered frame, and
    a watermark enable window ending exactly at content_duration still
    included that frame (frame timing is discrete; the boundary frame
    still qualifies), so the watermark got burned into the pixels that
    then got frozen and cloned - visibly stacking on top of the
    end-card text, the one thing this design explicitly rules out.
    """

    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(duration_seconds=60),
        orientation=AspectRatio.LANDSCAPE,
        platform=Platform.YOUTUBE,
    )

    command_plan, _ = execution.calls[0]
    match = re.search(r"enable='between\(t,4,(\d+)\)'", command_plan.filter_complex)
    assert match is not None
    watermark_end = int(match.group(1))
    assert watermark_end < 60, (
        "watermark must stop meaningfully before content_duration, not "
        "exactly at it, or the frame tpad freezes will still carry it"
    )


def test_no_end_card_or_watermark_when_platform_is_none() -> None:
    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(duration_seconds=60),
        orientation=AspectRatio.PORTRAIT,
        platform=None,
    )

    command_plan, total_duration_seconds = execution.calls[0]
    assert "tpad" not in command_plan.filter_complex
    assert "drawtext" not in command_plan.filter_complex
    assert total_duration_seconds == 60.0


def test_audio_is_padded_and_re_encoded_when_a_platform_is_chosen() -> None:
    """
    apad requires a real re-encode - a stream copy cannot extend an
    already-finalized audio stream the way the platform=None path's
    lossless -c:a copy can.
    """

    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(),
        orientation=AspectRatio.LANDSCAPE,
        platform=Platform.YOUTUBE,
    )

    command_plan, _ = execution.calls[0]
    assert "apad=pad_dur=5" in command_plan.filter_complex
    assert "copy" not in command_plan.arguments
    assert "aac" in command_plan.arguments


def test_portrait_with_a_platform_composes_reformat_and_branding() -> None:
    service, execution = _service()

    variant = service.build(
        job=_job(output_resolution="1920x1080"),
        render_result=_render_result(),
        orientation=AspectRatio.PORTRAIT,
        platform=Platform.TIKTOK,
    )

    command_plan, _ = execution.calls[0]
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in (
        command_plan.filter_complex
    )
    assert "tpad=stop_mode=clone" in command_plan.filter_complex
    assert "x=30:" in command_plan.filter_complex  # portrait watermark corner
    assert variant.orientation == AspectRatio.PORTRAIT
    assert variant.platform == Platform.TIKTOK
    assert "portrait" in variant.output_file
    assert "tiktok" in variant.output_file
