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
        "null",
        "asetpts",
        "volume",
        "anull",
        "amix",
        "alimiter",
    },
)

resolved_config = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=capabilities,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


def _build_graph_with_two_tracks() -> str:
    video = RenderNode(
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
    composition = RenderNode(
        node_type=RenderNodeType.VIDEO_COMPOSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={"output_resolution": "1920x1080", "frame_rate": 30},
    )
    voice = RenderNode(
        node_type=RenderNodeType.AUDIO_TRACK,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={
            "track_type": "voiceover",
            "source_file": "voice.wav",
            "volume": 1.0,
            "duck_under_voice": False,
        },
    )
    music = RenderNode(
        node_type=RenderNodeType.AUDIO_TRACK,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={
            "track_type": "background_music",
            "source_file": "music.mp3",
            "volume": 0.8,
            "duck_under_voice": False,
        },
    )
    audio_mix = RenderNode(
        node_type=RenderNodeType.AUDIO_MIX,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
    )
    output = RenderNode(
        node_type=RenderNodeType.OUTPUT,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
    )

    nodes = [video, composition, voice, music, audio_mix, output]

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
        output_node_id=str(output.id),
    )

    service = FilterGraphBuilderService()
    filter_graph = service.build(render_graph=graph, resolved_config=resolved_config)

    assert filter_graph.audio_output_label == "audio_final"
    assert filter_graph.is_valid is True

    return filter_graph.render_filter_complex()


def test_final_mix_is_routed_through_a_limiter() -> None:
    """
    Post-Script-Approval Production Plan, Phase 11: "Add loudness
    normalization targets and clipping prevention." Every mixed
    output - not only ducked ones - passes through a final `alimiter`
    before reaching the graph's public "audio_final" label, so summed,
    un-normalized tracks can never exceed full scale.
    """

    filter_complex = _build_graph_with_two_tracks()

    assert "alimiter" in filter_complex
    assert "[audio_mixed]alimiter=limit=1.0[audio_final]" in filter_complex


def test_amix_output_feeds_the_limiter_not_the_public_label_directly() -> None:
    filter_complex = _build_graph_with_two_tracks()

    assert "amix=inputs=2:duration=longest:normalize=0[audio_mixed]" in filter_complex
