from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.filter_graph import FilterGraph
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.filter_graph_builder_service import FilterGraphBuilderService

capabilities = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    ffmpeg_version="ffmpeg version 9.0",
    ffprobe_version="ffprobe version 9.0",
    encoders={"libx264", "aac"},
    filters={
        "scale",
        "fps",
        "format",
        "setpts",
        "concat",
        "null",
        "asetpts",
        "volume",
        "adelay",
        "anull",
        "amix",
        "afade",
        "aloop",
        "atrim",
    },
)

resolved_config = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=capabilities,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


def _video_clip() -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.VIDEO_CLIP,
        status=RenderNodeStatus.READY,
        scene_number=1,
        track_index=0,
        layer_index=0,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
        payload={"local_file": "scene_001.mp4"},
    )


def _video_composition() -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.VIDEO_COMPOSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
        payload={"output_resolution": "1920x1080", "frame_rate": 30},
    )


def _build_graph(*, audio_nodes: list[RenderNode]) -> FilterGraph:
    video = _video_clip()
    composition = _video_composition()
    audio_mix = RenderNode(
        node_type=RenderNodeType.AUDIO_MIX,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
    )
    output = RenderNode(
        node_type=RenderNodeType.OUTPUT,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
    )

    nodes = [video, composition, *audio_nodes, audio_mix, output]

    graph = RenderGraph(
        status=RenderGraphStatus.READY,
        nodes=nodes,
        edges=[],
        timeline_duration_seconds=40.0,
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

    service = FilterGraphBuilderService()

    return service.build(render_graph=graph, resolved_config=resolved_config)


def _music_node(*, loop_enabled: bool, duration_seconds: float = 40.0) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.AUDIO_TRACK,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=duration_seconds,
        duration_seconds=duration_seconds,
        payload={
            "track_type": "background_music",
            "source_file": "music_segment.mp3",
            "volume": 0.25,
            "loop_enabled": loop_enabled,
            "duck_under_voice": False,
        },
    )


def test_loop_disabled_produces_no_aloop_filter() -> None:
    graph = _build_graph(audio_nodes=[_music_node(loop_enabled=False)])
    filter_complex = graph.render_filter_complex()

    assert "aloop" not in filter_complex
    assert "atrim" not in filter_complex


def test_loop_enabled_produces_aloop_then_atrim_to_track_duration() -> None:
    graph = _build_graph(
        audio_nodes=[_music_node(loop_enabled=True, duration_seconds=40.0)]
    )
    filter_complex = graph.render_filter_complex()

    assert "aloop=loop=-1:size=" in filter_complex
    assert "atrim=duration=40" in filter_complex
    assert filter_complex.index("aloop") < filter_complex.index("atrim")
    assert graph.is_valid is True


def test_loop_enabled_with_zero_duration_is_skipped() -> None:
    graph = _build_graph(
        audio_nodes=[_music_node(loop_enabled=True, duration_seconds=0.0)]
    )
    filter_complex = graph.render_filter_complex()

    assert "aloop" not in filter_complex
