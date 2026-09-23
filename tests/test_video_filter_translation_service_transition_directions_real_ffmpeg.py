"""
REQ-6 (transition variety), 2026-09-22: real, non-mocked FFmpeg proof
that each new transition direction is genuinely accepted by FFmpeg's
own xfade filter (a made-up/misspelled transition name would fail the
real ffmpeg invocation immediately, unlike a unit test that only
checks the generated string) and that each one produces a real,
visually distinct mid-transition frame - proof these are actually
different effects, not five names silently collapsing to the same
transition.
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

_WIDTH = 640
_HEIGHT = 360
_CLIP_DURATION = 1.0
_TRANSITION_DURATION = 0.6
_OFFSET_SECONDS = _CLIP_DURATION - _TRANSITION_DURATION

_CAPABILITIES = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    filters={"xfade"},
)

_TRANSITION_TYPES = [
    "wipe_left",  # existing, control
    "slide_left",  # existing, control
    "wipe_up",
    "wipe_down",
    "slide_right",
    "slide_up",
    "slide_down",
]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:
        raise RuntimeError("Real transition-direction smoke requires ffmpeg.")

    return ffmpeg


def _create_textured_source(*, ffmpeg: str, pattern: str, output_file: Path) -> None:
    """
    A real, spatially-structured source (not a flat solid color) - a
    flat color makes wipe and slide along the SAME direction produce
    byte-identical mid-transition frames (both just show "half old
    color, half new color" with nothing to distinguish "wiped/
    revealed in place" from "physically slid into place"), which is a
    real property of flat content, not a bug in either transition.
    testsrc2's own real texture/gradient/moving elements make the two
    mechanically distinct effects genuinely distinguishable in pixels.
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
            f"{pattern}=size={_WIDTH}x{_HEIGHT}:rate=30:duration={_CLIP_DURATION}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            output_file.as_posix(),
        ]
    )


def _transition_node(*, transition_type: str) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.TRANSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=_OFFSET_SECONDS,
        end_time_seconds=_CLIP_DURATION,
        duration_seconds=_TRANSITION_DURATION,
        payload={
            "status": "ready",
            "placement": "between_scenes",
            "direction": "between",
            "preset_id": f"transition.{transition_type}",
            "transition_type": transition_type,
            "source_scene_number": 1,
            "target_scene_number": 2,
            "source_track_index": 0,
            "target_track_index": 0,
            "start_time_seconds": _OFFSET_SECONDS,
            "end_time_seconds": _CLIP_DURATION,
            "duration_seconds": _TRANSITION_DURATION,
            "overlap_start_seconds": _OFFSET_SECONDS,
            "overlap_end_seconds": _CLIP_DURATION,
            "intensity": "medium",
            "requires_overlap": True,
            "implementation": {
                "type": transition_type,
                "default_duration_seconds": _TRANSITION_DURATION,
            },
        },
    )


def _render_transition(
    *,
    ffmpeg: str,
    red_file: Path,
    blue_file: Path,
    transition_type: str,
    output_file: Path,
) -> None:
    service = VideoFilterTranslationService()

    translation = service.translate_transition(
        render_node=_transition_node(transition_type=transition_type),
        source_label="0:v",
        target_label="1:v",
        output_label="out",
        offset_seconds=_OFFSET_SECONDS,
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
            "-i",
            red_file.as_posix(),
            "-i",
            blue_file.as_posix(),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
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
            out.as_posix(),
        ]
    )


def test_every_new_transition_direction_is_accepted_by_real_ffmpeg_and_visually_distinct(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    red_file = tmp_path / "red.mp4"
    blue_file = tmp_path / "blue.mp4"

    _create_textured_source(ffmpeg=ffmpeg, pattern="testsrc2", output_file=red_file)
    _create_textured_source(ffmpeg=ffmpeg, pattern="smptebars", output_file=blue_file)

    midpoint_seconds = _OFFSET_SECONDS + (_TRANSITION_DURATION / 2.0)

    frame_bytes_by_type: dict[str, bytes] = {}

    for transition_type in _TRANSITION_TYPES:
        output_file = tmp_path / f"{transition_type}.mp4"

        # Real proof #1: FFmpeg genuinely accepts this transition name
        # - a made-up/misspelled xfade option would make this raise.
        _render_transition(
            ffmpeg=ffmpeg,
            red_file=red_file,
            blue_file=blue_file,
            transition_type=transition_type,
            output_file=output_file,
        )

        assert output_file.is_file()
        assert output_file.stat().st_size > 0

        frame_file = tmp_path / f"{transition_type}.png"

        _extract_frame(
            ffmpeg=ffmpeg,
            video_file=output_file,
            at_seconds=midpoint_seconds,
            out=frame_file,
        )

        frame_bytes_by_type[transition_type] = frame_file.read_bytes()

    # Real proof #2: every new direction produces a genuinely distinct
    # mid-transition frame - not five names silently collapsing to the
    # same underlying effect.
    seen: list[tuple[str, bytes]] = []

    for transition_type, frame_bytes in frame_bytes_by_type.items():
        for other_type, other_bytes in seen:
            assert frame_bytes != other_bytes, (
                f"{transition_type} produced an identical frame to "
                f"{other_type} - not a genuinely distinct transition."
            )

        seen.append((transition_type, frame_bytes))
