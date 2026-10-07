"""
Clips are fitted to the frame, not stretched (2026-10-07). Every clip used to be scaled to
the output size outright, so a landscape stock clip in a 9:16 video came out squashed and
a 4:3 clip in a 16:9 video stretched wide. A clip of the frame's shape is scaled as
before; a slightly different one fills the frame and is cropped; a very different one is
fitted whole over a blurred copy of itself.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.media_strategy import SceneSourceType
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.models.video_clip import VideoClip
from src.services.clip_fit_policy import ClipFit, clip_fit
from src.services.filter_graph_builder_service import FilterGraphBuilderService

# ------------------------------------------------------------------ the policy


def _fit(source: tuple[int | None, int | None], frame: tuple[int, int]) -> ClipFit:
    return clip_fit(
        source_width=source[0],
        source_height=source[1],
        frame_width=frame[0],
        frame_height=frame[1],
    )


def test_a_clip_of_the_frames_shape_is_just_scaled() -> None:
    assert _fit((1280, 720), (1920, 1080)) == ClipFit.SCALE
    assert _fit((720, 1280), (1080, 1920)) == ClipFit.SCALE
    assert _fit((1920, 1080), (1920, 1080)) == ClipFit.SCALE


def test_a_clip_of_unknown_size_keeps_the_plain_scaling() -> None:
    assert _fit((None, None), (1080, 1920)) == ClipFit.SCALE
    assert _fit((1280, None), (1080, 1920)) == ClipFit.SCALE
    assert _fit((0, 0), (1080, 1920)) == ClipFit.SCALE


def test_a_slightly_different_shape_fills_the_frame() -> None:
    assert _fit((1024, 768), (1920, 1080)) == ClipFit.COVER  # 4:3 in 16:9
    assert _fit((768, 1024), (1080, 1920)) == ClipFit.COVER  # 3:4 in 9:16


def test_a_very_different_shape_is_fitted_whole_over_a_blur() -> None:
    assert _fit((1920, 1080), (1080, 1920)) == ClipFit.BLUR_FIT  # landscape in 9:16
    assert _fit((1080, 1920), (1920, 1080)) == ClipFit.BLUR_FIT  # vertical in 16:9
    assert _fit((1080, 1080), (1920, 1080)) == ClipFit.BLUR_FIT  # square in 16:9


# ------------------------------------------------------------ the filter graph


def _resolved() -> FFmpegResolvedConfig:
    return FFmpegResolvedConfig(
        config=FFmpegConfig(),
        capabilities=FFmpegCapabilities(
            ffmpeg_available=True,
            ffprobe_available=True,
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
            ffmpeg_version="9.0",
            ffprobe_version="9.0",
            encoders={"libx264", "aac"},
            filters={
                "scale", "fps", "format", "setpts", "concat", "null", "crop",
                "split", "gblur", "overlay", "asetpts", "volume", "adelay",
                "anull", "amix",
            },
        ),
        selected_video_codec="libx264",
        selected_audio_codec="aac",
    )  # fmt: skip


def _filter_complex(
    *, source: tuple[int, int] | None, output: str = "1080x1920"
) -> str:
    def node(kind: RenderNodeType, **extra: object) -> RenderNode:
        return RenderNode(
            node_type=kind,
            status=RenderNodeStatus.READY,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
            duration_seconds=8.0,
            **extra,  # type: ignore[arg-type]
        )

    payload: dict[str, object] = {"local_file": "scene_001.mp4"}

    if source is not None:
        payload["source_width"], payload["source_height"] = source

    nodes = [
        node(RenderNodeType.VIDEO_CLIP, scene_number=1, track_index=0, layer_index=0, payload=payload),
        node(
            RenderNodeType.VIDEO_COMPOSITION,
            payload={"output_resolution": output, "frame_rate": 30},
        ),
        node(RenderNodeType.AUDIO_MIX),
        node(RenderNodeType.OUTPUT),
    ]  # fmt: skip
    graph = RenderGraph(
        status=RenderGraphStatus.READY,
        nodes=nodes,
        edges=[],
        timeline_duration_seconds=8.0,
        scene_count=1,
        node_count=len(nodes),
        edge_count=0,
        ready_node_count=len(nodes),
        executed_node_count=0,
        failed_node_count=0,
        is_valid=True,
        is_render_ready=True,
        output_node_id=str(nodes[-1].id),
    )

    return (
        FilterGraphBuilderService()
        .build(render_graph=graph, resolved_config=_resolved())
        .render_filter_complex()
    )


def test_a_clip_of_unknown_size_is_scaled_exactly_as_before() -> None:
    text = _filter_complex(source=None)

    assert "scale=w=1080:h=1920[" in text
    assert "force_original_aspect_ratio" not in text
    assert "gblur" not in text
    assert "crop" not in text


def test_a_clip_of_the_frames_shape_is_scaled_exactly_as_before() -> None:
    text = _filter_complex(source=(720, 1280))

    assert "force_original_aspect_ratio" not in text
    assert "gblur" not in text


def test_a_landscape_clip_in_a_vertical_frame_is_fitted_over_a_blurred_copy() -> None:
    text = _filter_complex(source=(1920, 1080))

    assert "split=2" in text
    assert "gblur=sigma=20" in text
    assert "force_original_aspect_ratio=increase" in text
    assert "force_original_aspect_ratio=decrease" in text
    assert "overlay=x=(W-w)/2:y=(H-h)/2" in text


def test_a_four_by_three_clip_in_a_landscape_frame_fills_it_by_cropping() -> None:
    text = _filter_complex(source=(1024, 768), output="1920x1080")

    assert "force_original_aspect_ratio=increase" in text
    assert "crop=w=1920:h=1080" in text
    assert "gblur" not in text


# ------------------------------------------------------ the render stage's probe


def test_the_render_reads_each_clips_real_size_and_does_not_touch_the_original(
    tmp_path: Path,
) -> None:
    from src.models.media_technical_validation import MediaTechnicalValidationResult
    from src.models.video_timeline import VideoTimeline
    from src.models.video_timeline_item import VideoTimelineItem
    from src.pipeline.render_stage import RenderPipelineStage

    class _Probe:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def validate(self, file_path: Path) -> MediaTechnicalValidationResult:
            self.asked.append(file_path.name)

            if file_path.name == "unreadable.mp4":
                return MediaTechnicalValidationResult(is_readable=False)

            return MediaTechnicalValidationResult(
                is_readable=True, width=1920, height=1080
            )

    def item(number: int, name: str | None) -> VideoTimelineItem:
        clip = VideoClip(
            scene_number=number,
            source_type=SceneSourceType.STOCK_FOOTAGE,
            duration_seconds=4,
            local_file=str(tmp_path / name) if name else None,
        )

        return VideoTimelineItem(
            scene_number=number,
            clip=clip,
            start_time_seconds=(number - 1) * 4.0,
            end_time_seconds=number * 4.0,
        )

    timeline = VideoTimeline(
        items=[
            item(1, "a.mp4"),
            item(2, "a.mp4"),
            item(3, "unreadable.mp4"),
            item(4, None),
        ]
    )
    probe = _Probe()
    stage = RenderPipelineStage.__new__(RenderPipelineStage)
    stage._media_validation_service = probe  # type: ignore[attr-defined]

    fitted = stage._with_clip_dimensions(timeline)  # type: ignore[attr-defined]  # noqa: SLF001

    assert [(i.clip.source_width, i.clip.source_height) for i in fitted.items] == [
        (1920, 1080),
        (1920, 1080),
        (None, None),  # unreadable: left to the plain scaling
        (None, None),  # no file at all
    ]
    assert probe.asked.count("a.mp4") == 1  # one probe per file, not per clip
    assert timeline.items[0].clip.source_width is None  # the original is untouched


# ------------------------------------------------------ real FFmpeg, real pixels

_NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="needs ffmpeg"
)


def _run_graph(
    tmp_path: Path, source_size: tuple[int, int], output: tuple[int, int]
) -> np.ndarray:
    """The clip's real filter graph (exactly as the builder writes it) run by FFmpeg on a
    clip made of a left half red and a right half blue; returns one output frame."""

    clip = tmp_path / "clip.mp4"
    width, height = source_size
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            f"color=c=red:size={width // 2}x{height}:rate=10:duration=1[l];"
            f"color=c=blue:size={width // 2}x{height}:rate=10:duration=1[r];[l][r]hstack",
            "-pix_fmt", "yuv420p", str(clip),
        ],
        check=True,
    )  # fmt: skip
    graph = _filter_complex(source=source_size, output=f"{output[0]}x{output[1]}")
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(clip),
            "-filter_complex", graph, "-map", "[video_final]", "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True,
    )  # fmt: skip

    assert result.returncode == 0, result.stderr.decode()[-600:]

    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(output[1], output[0], 3)


@_NEEDS_FFMPEG
def test_a_landscape_clip_in_a_vertical_frame_is_not_squashed(tmp_path: Path) -> None:
    """A red|blue landscape clip: stretched into 9:16 it would still be half red and
    half blue across the whole frame. Fitted, the picture sits in the middle band
    (red left, blue right) with the blurred copy above and below it."""

    frame = _run_graph(tmp_path, (640, 360), (216, 384))

    middle = frame[384 // 2]  # a row through the middle of the frame
    top = frame[3]  # a row near the top: only the blurred background there

    assert middle[20][0] > 150 and middle[20][2] < 100  # red on the left
    assert middle[-20][2] > 150 and middle[-20][0] < 100  # blue on the right
    # the picture is a 216x121 band: rows well above it are the blurred copy, which is
    # a smear of the same colours, not the sharp half-and-half of the clip itself
    assert abs(int(top[40][0]) - int(top[-40][0])) < 255
    assert frame.shape == (384, 216, 3)


@_NEEDS_FFMPEG
def test_a_four_by_three_clip_fills_a_landscape_frame_without_bars(
    tmp_path: Path,
) -> None:
    frame = _run_graph(tmp_path, (480, 360), (320, 180))

    assert frame[0][10][0] > 150  # the very top-left is picture (red), not a bar
    assert frame[-1][10][0] > 150
    assert frame[0][-10][2] > 150  # and the top-right corner is picture (blue)
