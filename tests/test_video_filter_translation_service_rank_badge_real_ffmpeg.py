"""
REQ-12 (top10 countdown rank cards), 2026-09-23: real, non-mocked
FFmpeg proof that the corner rank badge actually draws visible pixels
in the top-right corner of a scene's real footage - not just that the
drawtext options dict "looks right" in a unit test. Matches this
session's own established discipline for anything touching the filter
graph (see REQ-3's real letterbox vignette-angle-direction bug, only
caught by an actual render, never by a unit test that only checked
internal consistency).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.models.ffmpeg_config import FFmpegCapabilities
from src.models.render_graph import RenderNode, RenderNodeStatus, RenderNodeType
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

_WIDTH = 320
_HEIGHT = 240

_CAPABILITIES = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    filters={"drawtext", "null"},
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:
        raise RuntimeError("Real rank badge smoke requires ffmpeg.")

    return ffmpeg


def _create_white_source(*, ffmpeg: str, output_file: Path) -> None:
    """A real, flat white source - any darker pixels found in the
    badge's own top-right corner region were genuinely drawn by the
    badge's box/border, not already present in the source."""

    output_file.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:size={_WIDTH}x{_HEIGHT}:duration=1",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _rank_badge_node(*, rank_badge_text: str | None) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.VISUAL_EFFECT,
        status=RenderNodeStatus.READY,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=1.0,
        duration_seconds=1.0,
        payload={
            "scene_number": 1,
            "track_index": 0,
            "layer_index": 0,
            "preset_id": "visual.top10_rank_badge",
            "effect_type": "visual",
            "timing_mode": "full_scene",
            "intensity": "medium",
            "numeric_intensity_percent": None,
            "rank_badge_text": rank_badge_text,
            "start_time_seconds": 0.0,
            "end_time_seconds": 1.0,
            "duration_seconds": 1.0,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 1.0,
            "scene_duration_seconds": 1.0,
            "local_start_offset_seconds": 0.0,
            "relative_position_percent": None,
            "implementation": {},
        },
    )


def _render_badge(
    *, ffmpeg: str, source_file: Path, rank_badge_text: str, output_file: Path
) -> None:
    service = VideoFilterTranslationService()

    translation = service.translate_scene_node(
        render_node=_rank_badge_node(rank_badge_text=rank_badge_text),
        input_label="in",
        output_label="out",
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    assert not translation.skipped

    effect_expression = ";".join(
        filter_node.render_expression() for filter_node in translation.filters
    )
    filter_complex = f"[0:v]null[in];{effect_expression}"

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source_file.as_posix(),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            output_file.as_posix(),
        ]
    )


def _convert_to_ppm(*, ffmpeg: str, source_file: Path, output_file: Path) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source_file.as_posix(),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            output_file.as_posix(),
        ]
    )


def _read_ppm_rgb_pixels(ppm_file: Path) -> bytes:
    """Parse a raw P6 (binary RGB) PPM file into its raw byte stream."""

    data = ppm_file.read_bytes()

    assert data[:2] == b"P6", "Expected a raw RGB (P6) PPM file."

    index = 2
    tokens_found = 0
    token_start: int | None = None

    while tokens_found < 3:
        char = data[index : index + 1]

        if char.isspace():
            if token_start is not None:
                tokens_found += 1
                token_start = None
        elif token_start is None:
            token_start = index

        index += 1

    return data[index:]


def _corner_region_average_brightness(pixels: bytes) -> float:
    """Average brightness of the top-right quadrant, where the badge's
    x=w-text_w-margin / y=margin positioning places it."""

    quadrant_width = _WIDTH // 2
    quadrant_height = _HEIGHT // 2

    total = 0
    count = 0

    for row in range(quadrant_height):
        row_start = row * _WIDTH * 3

        for col in range(quadrant_width, _WIDTH):
            pixel_start = row_start + col * 3

            total += sum(pixels[pixel_start : pixel_start + 3])
            count += 3

    return total / count


def test_rank_badge_draws_visibly_darker_pixels_in_the_top_right_corner(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    source = tmp_path / "white.png"
    _create_white_source(ffmpeg=ffmpeg, output_file=source)

    control_output = tmp_path / "control.ppm"
    _convert_to_ppm(ffmpeg=ffmpeg, source_file=source, output_file=control_output)

    badged_output = tmp_path / "badged.ppm"
    _render_badge(
        ffmpeg=ffmpeg,
        source_file=source,
        rank_badge_text="10",
        output_file=badged_output,
    )

    control_brightness = _corner_region_average_brightness(
        _read_ppm_rgb_pixels(control_output)
    )
    badged_brightness = _corner_region_average_brightness(
        _read_ppm_rgb_pixels(badged_output)
    )

    # Real proof: the badge's semi-transparent black box + bordered
    # text measurably darkens the top-right corner relative to the
    # same region on an unmodified pure-white source.
    assert badged_brightness < control_brightness - 10


def test_rank_badge_with_no_text_is_skipped_not_rendered() -> None:
    service = VideoFilterTranslationService()

    translation = service.translate_scene_node(
        render_node=_rank_badge_node(rank_badge_text=None),
        input_label="in",
        output_label="out",
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    assert translation.skipped
    assert translation.filters == []
