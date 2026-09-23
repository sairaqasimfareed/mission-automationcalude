"""
REQ-00 Stage 1 (video-only render), 2026-09-21: FilterGraphBuilderService.
build() used to hard-require at least one AUDIO_TRACK node
(`"FFmpeg filter graph requires at least one audio source."`), and
unconditionally set audio_output_label="audio_final" even when no
audio chain would ever define that label - both wrong for a Stage 1
render graph, which deliberately has no AUDIO_TRACK/AUDIO_MIX nodes at
all (see RenderGraphBuilderService.build()'s own include_audio=False
mode). This file locks in the fix: build() must accept a render graph
with zero audio nodes and return a valid filter graph with a real
video_output_label but audio_output_label=None.
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
    filters={"scale", "fps", "format", "setpts", "concat", "null"},
)

_RESOLVED_CONFIG = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=_CAPABILITIES,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


def _video_only_render_graph() -> RenderGraph:
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

    video_2 = RenderNode(
        node_type=RenderNodeType.VIDEO_CLIP,
        status=RenderNodeStatus.READY,
        scene_number=2,
        track_index=0,
        layer_index=0,
        start_time_seconds=8.0,
        end_time_seconds=15.0,
        duration_seconds=7.0,
        payload={"local_file": "scene_002.mp4"},
    )

    video_composition = RenderNode(
        node_type=RenderNodeType.VIDEO_COMPOSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=15.0,
        duration_seconds=15.0,
        payload={"output_resolution": "1920x1080", "frame_rate": 30},
    )

    output = RenderNode(
        node_type=RenderNodeType.OUTPUT,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=15.0,
        duration_seconds=15.0,
        dependency_ids=[str(video_composition.id)],
    )

    nodes = [video_1, video_2, video_composition, output]

    return RenderGraph(
        status=RenderGraphStatus.READY,
        nodes=nodes,
        edges=[],
        timeline_duration_seconds=15.0,
        scene_count=2,
        node_count=len(nodes),
        edge_count=0,
        ready_node_count=len(nodes),
        executed_node_count=0,
        failed_node_count=0,
        is_valid=True,
        is_render_ready=True,
        output_node_id=str(output.id),
    )


def test_build_accepts_a_render_graph_with_no_audio_nodes() -> None:
    service = FilterGraphBuilderService()

    filter_graph = service.build(
        render_graph=_video_only_render_graph(),
        resolved_config=_RESOLVED_CONFIG,
    )

    assert filter_graph.is_valid is True
    assert filter_graph.video_output_label == "video_final"
    assert filter_graph.audio_output_label is None
    assert filter_graph.audio_chains == []


def test_video_only_filter_complex_has_no_audio_output_label() -> None:
    service = FilterGraphBuilderService()

    filter_graph = service.build(
        render_graph=_video_only_render_graph(),
        resolved_config=_RESOLVED_CONFIG,
    )

    filter_complex = filter_graph.render_filter_complex()

    assert "[video_final]" in filter_complex
    assert "[audio_final]" not in filter_complex
