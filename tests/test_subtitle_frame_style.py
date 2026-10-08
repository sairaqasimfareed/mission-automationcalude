"""
Subtitle size and position in a vertical (9:16) video (2026-10-08). The caption styles sit
60-90 px above the bottom edge at 48-60 px - in a 1080x1920 vertical video that is under
the platforms' own caption, account name and buttons (the bottom 15-25%), and small for a
phone held upright. For a vertical frame the text is larger and lifted; a landscape frame
is left exactly as the style defines it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
from src.models.media_technical_validation import MediaTechnicalValidationResult
from src.services.post_render_subtitle_burn_service import (
    PostRenderSubtitleBurnService,
)
from src.services.subtitle_frame_style import (
    PORTRAIT_BOTTOM_CLEARANCE,
    adapt_style_for_frame,
    is_portrait,
)
from tests.test_post_render_subtitle_burn_service import (
    _FakeCapabilityService,
    _FakeExecutionService,
)

_STYLE = {
    "fontcolor": "white",
    "fontsize": "48",
    "borderw": "2",
    "bordercolor": "black",
    "x": "(w-text_w)/2",
    "y": "h-text_h-60",
}


# ------------------------------------------------------------------ the style


def test_a_landscape_frame_keeps_the_style_exactly() -> None:
    assert adapt_style_for_frame(_STYLE, width=1920, height=1080) == _STYLE


def test_an_unknown_frame_size_keeps_the_style_exactly() -> None:
    assert adapt_style_for_frame(_STYLE, width=None, height=None) == _STYLE
    assert adapt_style_for_frame(_STYLE, width=1080, height=None) == _STYLE


def test_a_square_frame_is_not_treated_as_vertical() -> None:
    assert is_portrait(1080, 1080) is False
    assert adapt_style_for_frame(_STYLE, width=1080, height=1080) == _STYLE


def test_a_vertical_frame_gets_larger_text_lifted_clear_of_the_bottom() -> None:
    adapted = adapt_style_for_frame(_STYLE, width=1080, height=1920)

    assert adapted["fontsize"] == "62"  # 48 x 1.3
    assert adapted["borderw"] == "3"  # 2 x 1.3, rounded
    assert adapted["y"] == f"h-text_h-h*{PORTRAIT_BOTTOM_CLEARANCE}"
    # everything else about the look is the style's own
    assert adapted["fontcolor"] == "white"
    assert adapted["x"] == "(w-text_w)/2"
    assert _STYLE["y"] == "h-text_h-60"  # the original is not changed


def test_the_text_size_follows_the_frame_width() -> None:
    small = adapt_style_for_frame(_STYLE, width=720, height=1280)
    big = adapt_style_for_frame(_STYLE, width=1080, height=1920)

    assert int(small["fontsize"]) < int(big["fontsize"])
    assert small["fontsize"] == "42"  # 48 x (720/1080) x 1.3


def test_the_bigger_styles_scale_the_same_way() -> None:
    punchy = {**_STYLE, "fontsize": "60", "borderw": "5"}

    adapted = adapt_style_for_frame(punchy, width=1080, height=1920)

    assert adapted["fontsize"] == "78"
    assert adapted["borderw"] == "6"  # 5 x 1.3 = 6.5 -> 6 (banker's rounding is fine)


def test_a_style_without_a_size_does_not_break() -> None:
    adapted = adapt_style_for_frame({"x": "0"}, width=1080, height=1920)

    assert adapted["y"].startswith("h-text_h")
    assert "fontsize" not in adapted


# -------------------------------------------------------- inside the burn service


class _Probe:
    def __init__(self, width: int, height: int) -> None:
        self._size = (width, height)

    def validate(self, _path: Path) -> MediaTechnicalValidationResult:
        return MediaTechnicalValidationResult(
            is_readable=True,
            width=self._size[0],
            height=self._size[1],
            duration_seconds=2.0,
        )


def _filter(tmp_path: Path, width: int, height: int) -> str:
    execution = _FakeExecutionService()
    service = PostRenderSubtitleBurnService(
        capability_service=_FakeCapabilityService(),  # type: ignore[arg-type]
        execution_service=execution,  # type: ignore[arg-type]
        media_validation_service=_Probe(width, height),  # type: ignore[arg-type]
    )
    service.burn(
        input_video_file="in.mp4",
        cues=[AbsoluteSubtitleCue(text="Hi.", start_seconds=0.0, end_seconds=2.0)],
        output_file=str(tmp_path / "out.mp4"),
        video_duration_seconds=2.0,
    )

    return execution.calls[0][0].filter_complex


def test_a_landscape_video_is_burned_with_the_style_as_it_always_was(
    tmp_path: Path,
) -> None:
    text = _filter(tmp_path, 1920, 1080)

    assert "fontsize=48" in text
    assert "y=h-text_h-60" in text


def test_a_vertical_video_is_burned_with_larger_lifted_text(tmp_path: Path) -> None:
    text = _filter(tmp_path, 1080, 1920)

    assert "fontsize=62" in text
    assert f"y=h-text_h-h*{PORTRAIT_BOTTOM_CLEARANCE}" in text
    assert "y=h-text_h-60" not in text


# ------------------------------------------------------ real FFmpeg, real pixels


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_vertical_subtitles_sit_in_the_lower_middle_clear_of_the_bottom_quarter(
    tmp_path: Path,
) -> None:
    source = tmp_path / "vertical.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=gray:size=540x960:rate=5:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(source),
        ],
        check=True,
    )  # fmt: skip
    output = tmp_path / "out.mp4"

    result = PostRenderSubtitleBurnService().burn(
        input_video_file=str(source),
        cues=[
            AbsoluteSubtitleCue(
                text="Honey can help soothe a cough in adults tonight.",
                start_seconds=0.0,
                end_seconds=2.0,
            )
        ],
        output_file=str(output),
        video_duration_seconds=2.0,
    )

    assert result.success is True, result.error_message

    width, height = 540, 960
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", "1", "-i", str(output), "-frames:v", "1",
            "-vf", "format=gray", "-f", "rawvideo", "-",
        ],
        capture_output=True,
        check=True,
    ).stdout  # fmt: skip
    rows = [
        y
        for y in range(height)
        if any(
            raw[y * width + x] > 200 or raw[y * width + x] < 60 for x in range(width)
        )
    ]

    assert rows, "no subtitle was drawn"
    # the text's lowest pixel is at least ~22% of the frame above the bottom edge...
    assert max(rows) < height * 0.78
    # ...and it is in the lower half, not floating up the picture
    assert min(rows) > height * 0.5
