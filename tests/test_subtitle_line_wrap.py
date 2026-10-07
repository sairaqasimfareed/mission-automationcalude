"""
Subtitles in a vertical (9:16) video (2026-10-07): a line of up to 8 words filled a
1080-wide picture from edge to edge (measured on real pixels: x=22 to x=1056) and a longer
one was cut off. Lines too wide for the picture are broken into balanced rows.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
from src.services.post_render_subtitle_burn_service import (
    PostRenderSubtitleBurnService,
)
from src.services.subtitle_line_wrap import max_characters_per_line, wrap_for_frame

_LINE = "Honey can help soothe a cough in adults tonight."  # 48 characters


def test_a_wider_picture_fits_more_characters_on_a_row() -> None:
    narrow = max_characters_per_line(frame_width=1080, fontsize=48)
    wide = max_characters_per_line(frame_width=1920, fontsize=48)

    assert narrow < wide
    assert narrow == 37


def test_a_line_that_fits_is_left_exactly_as_it_is() -> None:
    assert wrap_for_frame("Short line.", frame_width=1080, fontsize=48) == "Short line."
    assert wrap_for_frame(_LINE, frame_width=1920, fontsize=48) == _LINE


def test_an_unknown_picture_width_changes_nothing() -> None:
    assert wrap_for_frame(_LINE, frame_width=None, fontsize=48) == _LINE
    assert wrap_for_frame(_LINE, frame_width=0, fontsize=48) == _LINE


def test_a_line_too_wide_for_a_vertical_picture_is_broken_into_balanced_rows() -> None:
    wrapped = wrap_for_frame(_LINE, frame_width=1080, fontsize=48)
    rows = wrapped.split("\n")

    assert len(rows) == 2
    assert all(len(row) <= 37 for row in rows)
    assert abs(len(rows[0]) - len(rows[1])) <= 12  # not one long row and a stub
    assert " ".join(rows) == _LINE  # no word lost or changed


def test_the_same_line_is_not_broken_in_a_landscape_picture() -> None:
    assert "\n" not in wrap_for_frame(_LINE, frame_width=1920, fontsize=48)


def test_a_bigger_font_breaks_a_line_sooner() -> None:
    line = "Honey can help soothe a cough."  # 30 characters

    assert "\n" not in wrap_for_frame(line, frame_width=1080, fontsize=48)
    assert "\n" in wrap_for_frame(line, frame_width=1080, fontsize=70)


def test_a_very_long_line_becomes_three_rows() -> None:
    long_line = " ".join(["remarkable"] * 11)  # 120 characters
    rows = wrap_for_frame(long_line, frame_width=1080, fontsize=48).split("\n")

    assert len(rows) == 4 or len(rows) == 3
    assert all(len(row) <= 37 for row in rows)


def test_a_single_word_longer_than_a_row_is_not_cut_in_half() -> None:
    word = "x" * 60
    wrapped = wrap_for_frame(word, frame_width=1080, fontsize=48)

    assert wrapped == word


def test_the_text_is_not_otherwise_changed() -> None:
    wrapped = wrap_for_frame(
        "Don't give honey to babies under 12 months - it's risky: botulism.",
        frame_width=1080,
        fontsize=48,
    )

    assert " ".join(wrapped.split()) == (
        "Don't give honey to babies under 12 months - it's risky: botulism."
    )


# ----------------------------------------------------------- real FFmpeg, real pixels


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg",
)
def test_a_burned_line_in_a_vertical_video_stays_inside_its_margins(
    tmp_path: Path,
) -> None:
    source = tmp_path / "vertical.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=gray:size=1080x1920:rate=10:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(source),
        ],
        check=True,
    )  # fmt: skip
    output = tmp_path / "out.mp4"

    result = PostRenderSubtitleBurnService().burn(
        input_video_file=str(source),
        cues=[AbsoluteSubtitleCue(text=_LINE, start_seconds=0.0, end_seconds=2.0)],
        output_file=str(output),
        video_duration_seconds=2.0,
    )

    assert result.success is True, result.error_message

    width, height = 1080, 240
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", "1", "-i", str(output), "-frames:v", "1",
            "-vf", f"crop={width}:{height}:0:1680,format=gray", "-f", "rawvideo", "-",
        ],
        capture_output=True,
        check=True,
    ).stdout  # fmt: skip
    columns = [
        x
        for x in range(width)
        if any(
            raw[y * width + x] > 200 or raw[y * width + x] < 60 for y in range(height)
        )
    ]

    assert columns, "no subtitle was drawn"
    # clear of the sides: the text (and its outline) keeps at least 8% on each side
    assert min(columns) > 0.08 * width
    assert max(columns) < 0.92 * width
