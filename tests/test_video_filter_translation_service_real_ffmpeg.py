"""
REQ-1/2 (tension-adaptive film grain/vignette), 2026-09-22: real,
non-mocked FFmpeg proof that a higher numeric_intensity_percent
produces a genuinely stronger visual effect in the actual rendered
pixels - not just a different string in a unit test. Reuses the real
production translate_scene_node() output (the exact FilterNode/
render_expression() the real render pipeline would emit) and feeds it
into a real ffmpeg invocation, then measures the real output frame.
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
    filters={"vignette", "noise", "null"},
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:
        raise RuntimeError("Real film-grain/vignette smoke requires ffmpeg.")

    return ffmpeg


def _create_flat_source(*, ffmpeg: str, color: str, output_file: Path) -> None:
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
            f"color=c={color}:size={_WIDTH}x{_HEIGHT}:duration=1",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _visual_effect_node(
    *, preset_id: str, numeric_intensity_percent: int | None
) -> RenderNode:
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
            "numeric_intensity_percent": numeric_intensity_percent,
            "start_time_seconds": 0.0,
            "end_time_seconds": 1.0,
            "duration_seconds": 1.0,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 1.0,
            "scene_duration_seconds": 1.0,
            "local_start_offset_seconds": 0.0,
            "relative_position_percent": None,
            "implementation": (
                {"effect": "vignette", "strength": 0.25}
                if preset_id == "visual.vignette_soft"
                else {"filter": "film_grain_light"}
            ),
        },
    )


def _render_with_effect(
    *, ffmpeg: str, source_file: Path, preset_id: str, numeric_intensity_percent: int
) -> Path:
    """Real ffmpeg render of one scene node's real translated filter."""

    service = VideoFilterTranslationService()

    translation = service.translate_scene_node(
        render_node=_visual_effect_node(
            preset_id=preset_id,
            numeric_intensity_percent=numeric_intensity_percent,
        ),
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

    output_file = source_file.with_name(
        f"{source_file.stem}_{preset_id.split('.')[-1]}_{numeric_intensity_percent}.pgm"
    )

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
            "gray",
            output_file.as_posix(),
        ]
    )

    return output_file


def _read_pgm_grayscale_pixels(pgm_file: Path) -> list[int]:
    """Parse a raw P5 PGM file into its grayscale byte values."""

    data = pgm_file.read_bytes()

    assert data[:2] == b"P5", "Expected a raw grayscale (P5) PGM file."

    # Header is "P5\n<width> <height>\n<maxval>\n" (whitespace-separated
    # tokens, comments not used by ffmpeg's pgm muxer) - walk past the
    # three header tokens to find where the raw pixel bytes start.
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

    return list(data[index:])


def _variance(values: list[int]) -> float:
    mean = sum(values) / len(values)

    return sum((value - mean) ** 2 for value in values) / len(values)


def test_real_film_grain_noise_is_visibly_stronger_at_higher_intensity(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    source_file = tmp_path / "flat_gray.png"
    _create_flat_source(ffmpeg=ffmpeg, color="gray", output_file=source_file)

    low_frame = _render_with_effect(
        ffmpeg=ffmpeg,
        source_file=source_file,
        preset_id="visual.film_grain_light",
        numeric_intensity_percent=0,
    )
    high_frame = _render_with_effect(
        ffmpeg=ffmpeg,
        source_file=source_file,
        preset_id="visual.film_grain_light",
        numeric_intensity_percent=100,
    )

    low_variance = _variance(_read_pgm_grayscale_pixels(low_frame))
    high_variance = _variance(_read_pgm_grayscale_pixels(high_frame))

    # A flat gray source has zero inherent variance - any variance in
    # the real rendered output is real injected grain noise, and a
    # genuinely stronger filter must inject visibly more of it.
    assert high_variance > low_variance * 2


def test_real_vignette_darkens_corners_more_at_higher_intensity(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    source_file = tmp_path / "flat_white.png"
    _create_flat_source(ffmpeg=ffmpeg, color="white", output_file=source_file)

    low_frame = _render_with_effect(
        ffmpeg=ffmpeg,
        source_file=source_file,
        preset_id="visual.vignette_soft",
        numeric_intensity_percent=0,
    )
    high_frame = _render_with_effect(
        ffmpeg=ffmpeg,
        source_file=source_file,
        preset_id="visual.vignette_soft",
        numeric_intensity_percent=100,
    )

    def _corner_brightness(pgm_file: Path) -> float:
        pixels = _read_pgm_grayscale_pixels(pgm_file)
        assert len(pixels) == _WIDTH * _HEIGHT

        patch = 20
        samples: list[int] = []

        for row in range(patch):
            for column in range(patch):
                samples.append(pixels[row * _WIDTH + column])  # top-left

        return sum(samples) / len(samples)

    def _center_brightness(pgm_file: Path) -> float:
        pixels = _read_pgm_grayscale_pixels(pgm_file)

        patch = 20
        top = (_HEIGHT - patch) // 2
        left = (_WIDTH - patch) // 2
        samples: list[int] = []

        for row in range(top, top + patch):
            for column in range(left, left + patch):
                samples.append(pixels[row * _WIDTH + column])

        return sum(samples) / len(samples)

    low_corner = _corner_brightness(low_frame)
    high_corner = _corner_brightness(high_frame)

    low_center = _center_brightness(low_frame)
    high_center = _center_brightness(high_frame)

    # A stronger real vignette must darken the corners visibly more...
    assert high_corner < low_corner - 10
    # ...while leaving the center comparatively untouched at both
    # intensities, confirming this is really a vignette (edge falloff)
    # and not just a uniform brightness change.
    assert low_center > 240
    assert high_center > 200
