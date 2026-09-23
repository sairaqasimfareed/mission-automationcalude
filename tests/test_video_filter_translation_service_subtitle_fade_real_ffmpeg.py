"""
REQ-5 (genre-aware subtitle styling), 2026-09-22: real, non-mocked
FFmpeg proof that a fade-enabled subtitle cue genuinely ramps in
(near-invisible right at cue start, fully visible by mid-cue), while a
cue with no animation preset pops to full brightness immediately -
using the exact production VideoFilterTranslationService.
translate_scene_node() output, not a hand-written filter string.
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

_WIDTH = 1280
_HEIGHT = 720

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
        raise RuntimeError("Real subtitle fade smoke requires ffmpeg.")

    return ffmpeg


def _create_dark_source(*, ffmpeg: str, duration: float, output_file: Path) -> None:
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
            f"color=c=black:size={_WIDTH}x{_HEIGHT}:duration={duration}",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _subtitle_node(*, animation_preset_id: str | None) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.SUBTITLE,
        status=RenderNodeStatus.READY,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=2.0,
        duration_seconds=2.0,
        payload={
            "scene_number": 1,
            "segment_index": 0,
            "text": "SUBTITLE FADE SMOKE",
            "preset_id": "subtitle.cinematic",
            "animation_preset_id": animation_preset_id,
            "burn_into_video": True,
            "timing_source": "estimated",
            "start_time_seconds": 0.0,
            "end_time_seconds": 2.0,
            "duration_seconds": 2.0,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 2.0,
            "local_start_offset_seconds": 0.0,
            "local_end_offset_seconds": 2.0,
            "word_count": 3,
        },
    )


def _render(
    *,
    ffmpeg: str,
    source_file: Path,
    animation_preset_id: str | None,
    output_file: Path,
) -> None:
    service = VideoFilterTranslationService()

    translation = service.translate_scene_node(
        render_node=_subtitle_node(animation_preset_id=animation_preset_id),
        input_label="0:v",
        output_label="out",
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    filter_complex = translation.filters[0].render_expression()

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-t",
            "2.0",
            "-i",
            source_file.as_posix(),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-t",
            "2.0",
            "-pix_fmt",
            "yuv420p",
            output_file.as_posix(),
        ]
    )


def _extract_frame(
    *, ffmpeg: str, video_file: Path, at_seconds: float, out: Path
) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            video_file.as_posix(),
            "-vframes",
            "1",
            "-pix_fmt",
            "gray",
            out.as_posix(),
        ]
    )


def _read_pgm_grayscale_pixels(pgm_file: Path) -> list[int]:
    data = pgm_file.read_bytes()

    assert data[:2] == b"P5"

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


def _brightness_sum(pgm_file: Path) -> int:
    return sum(_read_pgm_grayscale_pixels(pgm_file))


def test_fade_enabled_subtitle_is_dim_at_cue_start_and_bright_at_midpoint(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    source = tmp_path / "bg.png"
    _create_dark_source(ffmpeg=ffmpeg, duration=2.0, output_file=source)

    output_file = tmp_path / "fade.mp4"
    _render(
        ffmpeg=ffmpeg,
        source_file=source,
        animation_preset_id="animation.subtitle_fade",
        output_file=output_file,
    )

    start_frame = tmp_path / "start.pgm"
    mid_frame = tmp_path / "mid.pgm"

    # 0.02s in - well inside the 0.15s fade-in ramp, text should be
    # barely visible against the black background.
    _extract_frame(
        ffmpeg=ffmpeg, video_file=output_file, at_seconds=0.02, out=start_frame
    )
    # 1.0s - the cue's own midpoint, fully faded in.
    _extract_frame(ffmpeg=ffmpeg, video_file=output_file, at_seconds=1.0, out=mid_frame)

    start_brightness = _brightness_sum(start_frame)
    mid_brightness = _brightness_sum(mid_frame)

    assert start_brightness < mid_brightness * 0.5


def test_hard_cut_subtitle_is_already_bright_at_cue_start(tmp_path: Path) -> None:
    ffmpeg = _require_ffmpeg()

    source = tmp_path / "bg.png"
    _create_dark_source(ffmpeg=ffmpeg, duration=2.0, output_file=source)

    output_file = tmp_path / "hardcut.mp4"
    _render(
        ffmpeg=ffmpeg,
        source_file=source,
        animation_preset_id=None,
        output_file=output_file,
    )

    start_frame = tmp_path / "start.pgm"
    mid_frame = tmp_path / "mid.pgm"

    _extract_frame(
        ffmpeg=ffmpeg, video_file=output_file, at_seconds=0.02, out=start_frame
    )
    _extract_frame(ffmpeg=ffmpeg, video_file=output_file, at_seconds=1.0, out=mid_frame)

    start_brightness = _brightness_sum(start_frame)
    mid_brightness = _brightness_sum(mid_frame)

    # Real proof of the hard-cut behavior: text is already at (near)
    # full brightness right at cue start, not ramping up like the
    # fade case above.
    assert start_brightness > mid_brightness * 0.85
