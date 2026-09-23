"""
REQ-11 (genre-adaptive color grading), 2026-09-22: real, non-mocked
FFmpeg proof that the two new grades actually push color in the
correct real direction - not just that the eq/colorbalance dict
values "look right" in a unit test. Matches this session's own
established discipline for anything touching the filter graph (see
REQ-3's real letterbox vignette-angle-direction bug, only caught by an
actual render, never by a unit test that only checked internal
consistency).
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
    filters={"eq", "colorbalance", "null"},
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:
        raise RuntimeError("Real color grading smoke requires ffmpeg.")

    return ffmpeg


def _create_neutral_gray_source(*, ffmpeg: str, output_file: Path) -> None:
    """
    A real, neutral TRUE-midtone gray source (0x808080 = 128,128,128;
    R=G=B) - any real channel imbalance found in the GRADED output was
    genuinely introduced by the grade itself, not already present in
    the source. Deliberately 128 rather than X11's named "gray"
    (190,190,190, which sits closer to highlights) - colorbalance's
    shadow/midtone/highlight zones are luma-weighted, so a true
    midtone value is what actually exercises the "bm"/"rm" midtone
    adjustments these presets rely on for real, typical-brightness
    footage.
    """

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
            f"color=c=0x808080:size={_WIDTH}x{_HEIGHT}:duration=1",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _visual_effect_node(*, preset_id: str) -> RenderNode:
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
            "preset_id": preset_id,
            "effect_type": "visual",
            "timing_mode": "full_scene",
            "intensity": "medium",
            "numeric_intensity_percent": None,
            "start_time_seconds": 0.0,
            "end_time_seconds": 1.0,
            "duration_seconds": 1.0,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 1.0,
            "scene_duration_seconds": 1.0,
            "local_start_offset_seconds": 0.0,
            "relative_position_percent": None,
            "implementation": {"filter": preset_id.split(".")[-1]},
        },
    )


def _render_grade(
    *, ffmpeg: str, source_file: Path, preset_id: str, output_file: Path
) -> None:
    service = VideoFilterTranslationService()

    translation = service.translate_scene_node(
        render_node=_visual_effect_node(preset_id=preset_id),
        input_label="in",
        output_label="out",
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

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
    """A real, filter-free control baseline - the source's own raw
    pixels, with no VideoFilterTranslationService involvement at all
    ("visual.none" is a skip sentinel, not a renderable no-op filter,
    so it cannot itself produce a "control" pass)."""

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


def _channel_averages(pixels: bytes) -> tuple[float, float, float]:
    reds = pixels[0::3]
    greens = pixels[1::3]
    blues = pixels[2::3]

    return (
        sum(reds) / len(reds),
        sum(greens) / len(greens),
        sum(blues) / len(blues),
    )


def test_golden_hour_warm_measurably_shifts_toward_warm_and_away_from_blue(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    source = tmp_path / "gray.png"
    _create_neutral_gray_source(ffmpeg=ffmpeg, output_file=source)

    control_output = tmp_path / "control.ppm"
    _convert_to_ppm(ffmpeg=ffmpeg, source_file=source, output_file=control_output)

    graded_output = tmp_path / "golden_hour_warm.ppm"
    _render_grade(
        ffmpeg=ffmpeg,
        source_file=source,
        preset_id="visual.golden_hour_warm",
        output_file=graded_output,
    )

    control_r, control_g, control_b = _channel_averages(
        _read_ppm_rgb_pixels(control_output)
    )
    graded_r, graded_g, graded_b = _channel_averages(
        _read_ppm_rgb_pixels(graded_output)
    )

    # Real, directional proof: warm grading pushes red UP and blue
    # DOWN relative to the same neutral-gray source, ungraded.
    assert graded_r > control_r
    assert graded_b < control_b
    assert graded_r > graded_b


def test_clean_neutral_shows_no_meaningful_color_channel_skew(tmp_path: Path) -> None:
    ffmpeg = _require_ffmpeg()

    source = tmp_path / "gray.png"
    _create_neutral_gray_source(ffmpeg=ffmpeg, output_file=source)

    graded_output = tmp_path / "clean_neutral.ppm"
    _render_grade(
        ffmpeg=ffmpeg,
        source_file=source,
        preset_id="visual.clean_neutral",
        output_file=graded_output,
    )

    r, g, b = _channel_averages(_read_ppm_rgb_pixels(graded_output))

    # Real proof of genuine neutrality: every channel stays close to
    # every other channel (a few units of slack for the eq filter's
    # own real rounding noise - no colorbalance is applied at all for
    # this preset) - no real, deliberate color cast, unlike the
    # cool_blue_grade this preset replaced (which shows a real,
    # measurable skew in the test below).
    assert abs(r - g) <= 5
    assert abs(g - b) <= 5
    assert abs(r - b) <= 5


def test_cool_blue_grade_the_preset_medical_used_to_have_shows_a_real_blue_skew(
    tmp_path: Path,
) -> None:
    """
    Real contrast case: confirms visual.cool_blue_grade (still
    registered, just no longer used by genre.medical) genuinely DOES
    skew blue-up/red-down on the same neutral source - proving
    clean_neutral's own lack of skew above is a real, meaningful
    difference, not just "every grade looks the same on gray."
    """

    ffmpeg = _require_ffmpeg()

    source = tmp_path / "gray.png"
    _create_neutral_gray_source(ffmpeg=ffmpeg, output_file=source)

    control_output = tmp_path / "control.ppm"
    _convert_to_ppm(ffmpeg=ffmpeg, source_file=source, output_file=control_output)

    graded_output = tmp_path / "cool_blue_grade.ppm"
    _render_grade(
        ffmpeg=ffmpeg,
        source_file=source,
        preset_id="visual.cool_blue_grade",
        output_file=graded_output,
    )

    control_r, _control_g, control_b = _channel_averages(
        _read_ppm_rgb_pixels(control_output)
    )
    graded_r, _graded_g, graded_b = _channel_averages(
        _read_ppm_rgb_pixels(graded_output)
    )

    assert graded_b > control_b
    assert graded_r < control_r
