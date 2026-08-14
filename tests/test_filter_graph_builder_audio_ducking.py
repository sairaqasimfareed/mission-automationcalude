from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.filter_chain import FilterChain
from src.models.filter_graph import FilterGraph
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
        "sidechaincompress",
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
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={"local_file": "scene_001.mp4"},
    )


def _video_composition() -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.VIDEO_COMPOSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={"output_resolution": "1920x1080", "frame_rate": 30},
    )


def _build_graph(*, audio_nodes: list[RenderNode]) -> FilterGraph:
    video = _video_clip()
    composition = _video_composition()
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

    nodes = [video, composition, *audio_nodes, audio_mix, output]

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

    return service.build(render_graph=graph, resolved_config=resolved_config)


def _per_track_chains(filter_graph: FilterGraph) -> list[FilterChain]:
    return [
        chain for chain in filter_graph.audio_chains if "track_type" in chain.metadata
    ]


def _labels_for_track_type(filter_graph: FilterGraph, track_type: str) -> list[str]:
    return [
        chain.output_label
        for chain in _per_track_chains(filter_graph)
        if chain.metadata.get("track_type") == track_type and chain.output_label
    ]


def _chain_with_operation(filter_graph: FilterGraph, operation: str) -> FilterChain:
    return next(
        chain
        for chain in filter_graph.audio_chains
        if chain.metadata.get("operation") == operation
    )


# A duckable track (background_music, duck_under_voice=True) alongside a
# voiceover track must be routed through sidechaincompress, with the
# voiceover as the sidechain trigger, and the final amix must pick up the
# ducked output rather than the raw normalized label.
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
        "volume": 0.25,
        "duck_under_voice": True,
    },
)

sfx = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=2.0,
    end_time_seconds=4.0,
    duration_seconds=2.0,
    payload={
        "track_type": "sound_effect",
        "source_file": "creak.mp3",
        "volume": 0.7,
        "duck_under_voice": False,
    },
)

filter_graph = _build_graph(audio_nodes=[voice, music, sfx])
filter_complex = filter_graph.render_filter_complex()

print("Ducking filter complex:", filter_complex)

assert filter_graph.is_valid is True
assert "sidechaincompress" in filter_complex

# Exactly one duckable track (music) -> exactly one sidechaincompress node.
assert filter_complex.count("sidechaincompress") == 1

voice_labels = _labels_for_track_type(filter_graph, "voiceover")
music_labels = _labels_for_track_type(filter_graph, "background_music")
sfx_labels = _labels_for_track_type(filter_graph, "sound_effect")
assert len(voice_labels) == 1
assert len(music_labels) == 1
assert len(sfx_labels) == 1

duck_chain = _chain_with_operation(filter_graph, "duck_under_voice")
assert duck_chain.input_labels == [music_labels[0], voice_labels[0]]
ducked_label = duck_chain.output_label
assert ducked_label is not None

# The ducked output, not the raw normalized music label, must reach the
# final mix - and the raw music label must not appear there directly.
final_mix_chain = _chain_with_operation(filter_graph, "audio_mix")
assert ducked_label in final_mix_chain.input_labels
assert music_labels[0] not in final_mix_chain.input_labels
assert voice_labels[0] in final_mix_chain.input_labels
assert sfx_labels[0] in final_mix_chain.input_labels
assert len(final_mix_chain.input_labels) == 3


# No duck_under_voice tracks at all -> sidechaincompress must not appear,
# and the flat amix behavior from before this feature must be unchanged.
plain_voice = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "track_type": "voiceover",
        "source_file": "voice.wav",
        "volume": 1.0,
    },
)

plain_sfx = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=2.0,
    end_time_seconds=4.0,
    duration_seconds=2.0,
    payload={
        "track_type": "sound_effect",
        "source_file": "creak.mp3",
        "volume": 0.7,
        "duck_under_voice": False,
    },
)

no_duck_graph = _build_graph(audio_nodes=[plain_voice, plain_sfx])
no_duck_complex = no_duck_graph.render_filter_complex()

assert "sidechaincompress" not in no_duck_complex

no_duck_mix_chain = _chain_with_operation(no_duck_graph, "audio_mix")
assert len(no_duck_mix_chain.input_labels) == 2
assert set(no_duck_mix_chain.input_labels) == {
    label
    for track_type in ("voiceover", "sound_effect")
    for label in _labels_for_track_type(no_duck_graph, track_type)
}


# Multiple voiceover tracks alongside a duckable track must be mixed into
# one voice bus first, and the sidechaincompress must use that bus rather
# than either voiceover track directly.
voice_a = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=4.0,
    duration_seconds=4.0,
    payload={
        "track_type": "voiceover",
        "source_file": "voice_scene_1.wav",
        "volume": 1.0,
    },
)

voice_b = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=4.0,
    end_time_seconds=8.0,
    duration_seconds=4.0,
    payload={
        "track_type": "voiceover",
        "source_file": "voice_scene_2.wav",
        "volume": 1.0,
    },
)

duckable_music = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "track_type": "background_music",
        "source_file": "music.mp3",
        "volume": 0.25,
        "duck_under_voice": True,
    },
)

multi_voice_graph = _build_graph(audio_nodes=[voice_a, voice_b, duckable_music])
multi_voice_complex = multi_voice_graph.render_filter_complex()

print("Multi-voice ducking filter complex:", multi_voice_complex)

# One amix to build the voice bus, one amix for the final mix.
assert multi_voice_complex.count("amix") == 2
assert "sidechaincompress" in multi_voice_complex

multi_voice_labels = _labels_for_track_type(multi_voice_graph, "voiceover")
multi_music_labels = _labels_for_track_type(multi_voice_graph, "background_music")
assert len(multi_voice_labels) == 2
assert len(multi_music_labels) == 1

voice_bus_chain = _chain_with_operation(multi_voice_graph, "voice_bus_mix")
assert set(voice_bus_chain.input_labels) == set(multi_voice_labels)
voice_bus_label = voice_bus_chain.output_label
assert voice_bus_label is not None
assert f"[{voice_bus_label}]" in multi_voice_complex

multi_duck_chain = _chain_with_operation(multi_voice_graph, "duck_under_voice")
assert multi_duck_chain.input_labels == [multi_music_labels[0], voice_bus_label]

multi_final_mix_chain = _chain_with_operation(multi_voice_graph, "audio_mix")
assert multi_duck_chain.output_label in multi_final_mix_chain.input_labels
assert multi_music_labels[0] not in multi_final_mix_chain.input_labels
assert set(multi_voice_labels).issubset(set(multi_final_mix_chain.input_labels))

print("ALL DUCKING ASSERTIONS PASSED")
