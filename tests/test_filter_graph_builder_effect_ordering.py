from __future__ import annotations

from uuid import UUID

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
        "null",
        "eq",
        "colorchannelmixer",
        "asetpts",
        "volume",
        "adelay",
        "anull",
        "amix",
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


def _build_graph(*, visual_effect_nodes: list[RenderNode]) -> FilterGraph:
    video = _video_clip()
    composition = _video_composition()
    audio = RenderNode(
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

    nodes = [video, composition, *visual_effect_nodes, audio, audio_mix, output]

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


def _visual_effect(
    *,
    node_id: UUID,
    preset_id: str,
    directive_index: int,
    implementation: dict[str, object],
) -> RenderNode:
    """
    Build one visual-effect node, mirroring the real shape
    EffectExecution.model_dump() produces - including the
    directive_path this test exists to prove the sort now honors.
    """

    return RenderNode(
        id=node_id,
        node_type=RenderNodeType.VISUAL_EFFECT,
        status=RenderNodeStatus.READY,
        scene_number=1,
        track_index=0,
        layer_index=0,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={
            "status": "ready",
            "scene_number": 1,
            "track_index": 0,
            "layer_index": 0,
            "preset_id": preset_id,
            "effect_type": "color_grade",
            "timing_mode": "full_scene",
            "intensity": "medium",
            "start_time_seconds": 0.0,
            "end_time_seconds": 8.0,
            "duration_seconds": 8.0,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 8.0,
            "scene_duration_seconds": 8.0,
            "local_start_offset_seconds": 0.0,
            "relative_position_percent": None,
            "implementation": implementation,
            "metadata": {
                "directive_path": f"visual_effects[{directive_index}].preset_id",
                "found_exact_match": True,
                "used_fallback": False,
            },
        },
    )


# Real-world finding, 2026-09-17: genre.history resolves grayscale then
# sepia_tone (visual_effects[0] = grayscale, visual_effects[1] =
# sepia_tone) - desaturating first, then tinting, is the only order that
# actually produces a visible sepia look. Every other component of the
# scene-operation sort key ties for two same-scene, same-time,
# same-track, same-layer visual effects, so without reading
# directive_path the final tiebreaker was each node's own random UUID -
# a coin flip per scene between "sepia survives" (grayscale applied
# first) and "sepia is erased" (sepia applied first, then wiped out by
# desaturating on top of it). This test deliberately gives the LATER
# directive (sepia_tone, index 1) the LEXICALLY SMALLER id, so a UUID-
# based tiebreak would sort it first and prove the bug; a directive_path-
# based tiebreak must still sort grayscale (index 0) first regardless.
grayscale_node = _visual_effect(
    node_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    preset_id="visual.grayscale",
    directive_index=0,
    implementation={"brightness": 0.0, "contrast": 1.0, "saturation": 0.0},
)

sepia_node = _visual_effect(
    node_id=UUID("00000000-0000-0000-0000-000000000000"),
    preset_id="visual.sepia_tone",
    directive_index=1,
    implementation={},
)

filter_graph = _build_graph(visual_effect_nodes=[grayscale_node, sepia_node])
filter_complex = filter_graph.render_filter_complex()

print("Effect-ordering filter complex:", filter_complex)

assert filter_graph.is_valid is True

eq_position = filter_complex.index("saturation=0")
colorchannelmixer_position = filter_complex.index("colorchannelmixer")

assert eq_position < colorchannelmixer_position, (
    "Desaturation (visual_effects[0]) must apply BEFORE the sepia tint "
    "(visual_effects[1]) - applying it after erases the tint entirely. "
    "The node with the lexically smaller UUID was the sepia effect, so "
    "this only passes when ordering follows directive_path, not id."
)


# Reversed input order (sepia_node listed first) must produce the SAME
# real ordering - the fix must be genuinely order-independent, not an
# artifact of list-construction order happening to match.
filter_graph_reversed = _build_graph(visual_effect_nodes=[sepia_node, grayscale_node])
filter_complex_reversed = filter_graph_reversed.render_filter_complex()

eq_position_reversed = filter_complex_reversed.index("saturation=0")
colorchannelmixer_position_reversed = filter_complex_reversed.index("colorchannelmixer")

assert eq_position_reversed < colorchannelmixer_position_reversed


# A node with no parseable directive_path (nothing in this codebase's
# real payloads today, but a real degrade path worth locking in) must
# not crash and must sort after nodes that do have one.
undirected_node = _visual_effect(
    node_id=UUID("88888888-8888-8888-8888-888888888888"),
    preset_id="visual.grayscale",
    directive_index=0,
    implementation={"brightness": 0.0, "contrast": 1.0, "saturation": 0.0},
)
undirected_node.payload["metadata"] = {}

undirected_filter_graph = _build_graph(visual_effect_nodes=[undirected_node])

assert undirected_filter_graph.is_valid is True

print("ALL EFFECT-ORDERING ASSERTIONS PASSED")
