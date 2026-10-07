"""
Export variants with an operator-uploaded watermark image and/or CTA end
clip, 2026-10-02: real FFmpeg, no mocking. The unit tests in
test_export_variant_render_service.py prove the command shape; these
prove the produced file is actually right - correct total duration,
audio the same length as the video (no desync at the join), the clip's
own pixels at the end, and the watermark's own pixels in the right
corner.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.enums import Platform
from src.models.render_result import RenderResult
from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob
from src.services.export_variant_render_service import ExportVariantRenderService

_WIDTH = 640
_HEIGHT = 360
_MAIN_SECONDS = 3
_CLIP_SECONDS = 2

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Real export-variant upload tests require ffmpeg and ffprobe.",
)


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=True, capture_output=True)


def _ffmpeg(*args: str) -> None:
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def _make_main_video(path: Path) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={_WIDTH}x{_HEIGHT}:rate=30:duration={_MAIN_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={_MAIN_SECONDS}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )


def _make_clip(path: Path, *, size: str, rate: int, with_audio: bool) -> None:
    arguments = [
        "-f",
        "lavfi",
        "-i",
        f"color=c=red:size={size}:rate={rate}:duration={_CLIP_SECONDS}",
    ]

    if with_audio:
        arguments += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=880:duration={_CLIP_SECONDS}",
            "-c:a",
            "aac",
        ]

    arguments += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    _ffmpeg(*arguments)


def _make_watermark(path: Path) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=magenta:size=100x100",
        "-frames:v",
        "1",
        str(path),
    )


def _probe(path: Path) -> dict[str, dict[str, float]]:
    raw = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration,width,height",
            "-of",
            "json",
            str(path),
        ]
    ).stdout
    streams = json.loads(raw)["streams"]

    return {
        stream["codec_type"]: {
            key: float(value)
            for key, value in stream.items()
            if key in {"duration", "width", "height"}
        }
        for stream in streams
    }


def _pixel(path: Path, *, at_seconds: float, x: int, y: int) -> tuple[int, int, int]:
    raw = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(at_seconds),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"format=rgb24,crop=1:1:{x}:{y}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    ).stdout

    return raw[0], raw[1], raw[2]


def _is_red(pixel: tuple[int, int, int]) -> bool:
    return pixel[0] > 200 and pixel[1] < 60 and pixel[2] < 60


def _is_magenta(pixel: tuple[int, int, int]) -> bool:
    """Magenta as seen through the watermark's 70% opacity (a pure magenta pixel is
    blended with the video behind it, e.g. (175, 75, 253))."""

    return pixel[0] > 140 and pixel[1] < 130 and pixel[2] > 140


def _build(
    tmp_path: Path,
    *,
    watermark: Path | None = None,
    clip: Path | None = None,
    orientation: AspectRatio = AspectRatio.LANDSCAPE,
) -> Path:
    main = tmp_path / "main.mp4"

    if not main.exists():
        _make_main_video(main)

    job = VideoJob(
        project_name="Real Upload Test",
        channel_name="Test Channel",
        niche="test",
        topic="Test topic",
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        cta_watermark_image_path=str(watermark) if watermark else None,
        cta_end_clip_path=str(clip) if clip else None,
    )
    variant = ExportVariantRenderService().build(
        job=job,
        render_result=RenderResult(
            success=True,
            output_file=str(main),
            render_engine="ffmpeg",
            duration_seconds=_MAIN_SECONDS,
        ),
        orientation=orientation,
        platform=Platform.YOUTUBE,
    )

    assert variant.output_file is not None

    return Path(variant.output_file)


def test_cta_clip_with_audio_is_appended_in_sync(tmp_path: Path) -> None:
    clip = tmp_path / "cta.mp4"
    _make_clip(clip, size="320x240", rate=25, with_audio=True)

    output = _build(tmp_path, clip=clip)
    streams = _probe(output)

    expected = _MAIN_SECONDS + _CLIP_SECONDS

    assert streams["video"]["duration"] == pytest.approx(expected, abs=0.25)
    assert streams["audio"]["duration"] == pytest.approx(expected, abs=0.25)
    assert (streams["video"]["width"], streams["video"]["height"]) == (_WIDTH, _HEIGHT)
    # The final seconds are the uploaded clip, not a blank/frozen frame:
    # the 4:3 red clip is letterboxed, so the frame centre is red.
    assert _is_red(
        _pixel(output, at_seconds=expected - 0.5, x=_WIDTH // 2, y=_HEIGHT // 2)
    )
    # ...and the content before it is not.
    assert not _is_red(_pixel(output, at_seconds=1.0, x=_WIDTH // 2, y=_HEIGHT // 2))


def test_cta_clip_without_audio_still_keeps_audio_aligned(tmp_path: Path) -> None:
    clip = tmp_path / "cta_silent.mp4"
    _make_clip(clip, size="640x360", rate=30, with_audio=False)

    streams = _probe(_build(tmp_path, clip=clip))
    expected = _MAIN_SECONDS + _CLIP_SECONDS

    assert streams["video"]["duration"] == pytest.approx(expected, abs=0.25)
    assert streams["audio"]["duration"] == pytest.approx(expected, abs=0.25)


def test_no_generated_end_card_text_when_a_cta_clip_is_used(tmp_path: Path) -> None:
    """The generated end-card is 5s; a 2s clip must produce 2s, not 5."""

    clip = tmp_path / "cta.mp4"
    _make_clip(clip, size="640x360", rate=30, with_audio=True)

    streams = _probe(_build(tmp_path, clip=clip))

    assert streams["video"]["duration"] < _MAIN_SECONDS + 3.0


def test_watermark_image_appears_in_the_landscape_bottom_right_corner(
    tmp_path: Path,
) -> None:
    watermark = tmp_path / "wm.png"
    _make_watermark(watermark)

    output = _build(tmp_path, watermark=watermark)

    # 15% of 640 = 96px wide; bottom-right with a 30px margin.
    centre_x = _WIDTH - 30 - 48
    centre_y = _HEIGHT - 30 - 48

    assert _is_magenta(_pixel(output, at_seconds=0.3, x=centre_x, y=centre_y))
    # Not in the opposite corner.
    assert not _is_magenta(_pixel(output, at_seconds=0.3, x=60, y=centre_y))


def test_watermark_image_is_bottom_left_for_portrait(tmp_path: Path) -> None:
    watermark = tmp_path / "wm.png"
    _make_watermark(watermark)

    output = _build(tmp_path, watermark=watermark, orientation=AspectRatio.PORTRAIT)
    streams = _probe(output)

    assert (streams["video"]["width"], streams["video"]["height"]) == (
        _HEIGHT,
        _WIDTH,
    )
    # Portrait frame is 360x640; width is 15% of 360 = 54px (even-rounded).
    assert _is_magenta(_pixel(output, at_seconds=0.3, x=30 + 27, y=_WIDTH - 30 - 27))


def test_watermark_does_not_cover_the_cta_clip(tmp_path: Path) -> None:
    watermark = tmp_path / "wm.png"
    clip = tmp_path / "cta.mp4"
    _make_watermark(watermark)
    _make_clip(clip, size="640x360", rate=30, with_audio=True)

    output = _build(tmp_path, watermark=watermark, clip=clip)
    corner = (_WIDTH - 30 - 48, _HEIGHT - 30 - 48)
    end = _MAIN_SECONDS + _CLIP_SECONDS - 0.5

    # Watermark over the content, then the clip is plain red edge to edge.
    assert _is_magenta(_pixel(output, at_seconds=1.0, x=corner[0], y=corner[1]))
    assert _is_red(_pixel(output, at_seconds=end, x=corner[0], y=corner[1]))


def test_a_missing_upload_is_an_error_not_a_silent_default(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not be found"):
        _build(tmp_path, clip=tmp_path / "gone.mp4")


def test_an_unreadable_cta_clip_is_an_error_not_a_silent_default(
    tmp_path: Path,
) -> None:
    not_a_video = tmp_path / "notes.mp4"
    not_a_video.write_text("this is not a video", encoding="utf-8")

    with pytest.raises(ValueError, match="not a readable video"):
        _build(tmp_path, clip=not_a_video)
