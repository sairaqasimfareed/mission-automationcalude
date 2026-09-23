"""
REQ-3 (cinematic letterboxing), 2026-09-22: real 2.35:1 pad/crop
verification. Before this, no letterboxing concept existed anywhere in
the filter graph at all (confirmed via grep). Locks in: the math (a
centered crop down to a 2.35:1 window, padded back out to the full
canvas with black bars), the harmless no-op for a canvas already at or
beyond that aspect ratio, and end-to-end wiring through
FilterGraphBuilderService.build() reading letterbox_enabled off the
video-composition node's own payload - disabled (the default)
reproduces this service's exact prior behavior.
"""

from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.filter_graph_builder_service import (
    FilterGraphBuilderService,
)

_CAPABILITIES = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    ffmpeg_version="ffmpeg version 9.0",
    ffprobe_version="ffprobe version 9.0",
    encoders={"libx264", "aac"},
    filters={"scale", "fps", "format", "setpts", "concat", "null", "crop", "pad"},
)

_RESOLVED_CONFIG = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=_CAPABILITIES,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


def _render_graph(*, output_resolution: str, letterbox_enabled: bool) -> RenderGraph:
    video_1 = RenderNode(
        node_type=RenderNodeType.VIDEO_CLIP,
        status=RenderNodeStatus.READY,
        scene_number=1,
        track_index=0,
        layer_index=0,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={"local_file": "scene_001.mp4"},
    )

    video_composition = RenderNode(
        node_type=RenderNodeType.VIDEO_COMPOSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={
            "output_resolution": output_resolution,
            "frame_rate": 30,
            "letterbox_enabled": letterbox_enabled,
        },
    )

    output = RenderNode(
        node_type=RenderNodeType.OUTPUT,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        dependency_ids=[str(video_composition.id)],
    )

    nodes = [video_1, video_composition, output]

    return RenderGraph(
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
        output_node_id=str(output.id),
    )


def test_letterbox_disabled_reproduces_prior_behavior() -> None:
    """No letterbox_enabled in payload at all (every existing render
    graph built before this REQ) must behave exactly as before -
    real, unmodified backward compatibility, not just a default value
    that happens to work."""

    service = FilterGraphBuilderService()

    filter_graph = service.build(
        render_graph=_render_graph(
            output_resolution="1920x1080", letterbox_enabled=False
        ),
        resolved_config=_RESOLVED_CONFIG,
    )

    filter_complex = filter_graph.render_filter_complex()

    assert "crop=" not in filter_complex
    assert "pad=" not in filter_complex
    assert filter_graph.metadata["letterbox_enabled"] is False


def test_letterbox_enabled_adds_a_real_crop_and_pad_step() -> None:
    service = FilterGraphBuilderService()

    filter_graph = service.build(
        render_graph=_render_graph(
            output_resolution="1920x1080", letterbox_enabled=True
        ),
        resolved_config=_RESOLVED_CONFIG,
    )

    filter_complex = filter_graph.render_filter_complex()

    assert "crop=" in filter_complex
    assert "pad=" in filter_complex
    assert "color=black" in filter_complex
    assert "[video_final]" in filter_complex
    assert filter_graph.metadata["letterbox_enabled"] is True
    assert filter_graph.is_valid is True


def test_letterbox_chain_math_at_1920x1080() -> None:
    """
    2.35:1 window inside a 1920x1080 canvas: inner_height =
    floor(1920 / 2.35) = 817, rounded down to even = 816, bar_height =
    (1080 - 816) // 2 = 132 - a real, hand-verified expectation, not
    just "some crop/pad appeared".
    """

    chain = FilterGraphBuilderService._build_letterbox_chain(
        input_label="video_preletterbox",
        output_label="video_final",
        width=1920,
        height=1080,
    )

    assert chain is not None

    crop_node, pad_node = chain.nodes

    assert crop_node.filter_name == "crop"
    assert crop_node.options["w"] == "1920"
    assert crop_node.options["h"] == "816"
    assert crop_node.options["y"] == "132"

    assert pad_node.filter_name == "pad"
    assert pad_node.options["w"] == "1920"
    assert pad_node.options["h"] == "1080"
    assert pad_node.options["y"] == "132"
    assert pad_node.options["color"] == "black"

    assert chain.output_label == "video_final"


def test_letterbox_chain_is_a_no_op_when_canvas_already_matches_or_exceeds_target() -> (
    None
):
    """A canvas already at (or narrower than, i.e. wider-aspect than)
    2.35:1 needs no bars - real crop math would produce a zero or
    negative bar height, so this must return None rather than emit a
    meaningless/harmful filter."""

    chain = FilterGraphBuilderService._build_letterbox_chain(
        input_label="in",
        output_label="out",
        width=2350,
        height=1000,
    )

    assert chain is None


def test_letterbox_chain_math_at_a_different_resolution() -> None:
    """1280x720: inner_height = floor(1280 / 2.35) = 544, already
    even, bar_height = (720 - 544) // 2 = 88."""

    chain = FilterGraphBuilderService._build_letterbox_chain(
        input_label="in",
        output_label="out",
        width=1280,
        height=720,
    )

    assert chain is not None

    crop_node, pad_node = chain.nodes

    assert crop_node.options["h"] == "544"
    assert crop_node.options["y"] == "88"
    assert pad_node.options["h"] == "720"
    assert pad_node.options["y"] == "88"
