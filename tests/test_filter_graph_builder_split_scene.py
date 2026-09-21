"""
Phase 5 (multi-clip scene splitting), real-world finding, 2026-09-21:
FilterGraphBuilderService assumed exactly one video node per
scene_number throughout - a bare-int-keyed scene_final_labels/
scene_durations dict, FFmpeg filter labels embedding only scene_number
("scene_9301_scaled"), and _transition_between_scenes matching only on
scene_number. A real split scene's own two sub-clips share one
scene_number (distinguished only by clip_sequence_index), so every one
of these would have collided or crashed outright - confirmed directly
by running a real split-scene job through the full render path before
this fix existed. This file locks in the composite-key fix with real,
synthetic render-graph nodes shaped exactly like what
RenderGraphBuilderService now produces for a real split scene.
"""

from __future__ import annotations

from src.models.ffmpeg_config import FFmpegCapabilities
from src.models.render_graph import (
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
    filters={"fade", "xfade", "null"},
)

_SCENE_NUMBER = 9301


def _video_node(*, clip_sequence_index: int, duration_seconds: float) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.VIDEO_CLIP,
        status=RenderNodeStatus.READY,
        scene_number=_SCENE_NUMBER,
        clip_sequence_index=clip_sequence_index,
        track_index=0,
        layer_index=0,
        start_time_seconds=clip_sequence_index * duration_seconds,
        end_time_seconds=(clip_sequence_index + 1) * duration_seconds,
        duration_seconds=duration_seconds,
        payload={"local_file": f"sub_{clip_sequence_index}.mp4", "source_url": None},
    )


def _seam_transition_node(*, duration_seconds: float = 1.0) -> RenderNode:
    """A real intra-scene seam transition, shaped exactly like what
    TransitionExecutionService/RenderGraphBuilderService produce for
    two consecutive sub-clips of one split scene: source and target
    share one scene_number, distinguished only by clip_sequence_index."""

    return RenderNode(
        node_type=RenderNodeType.TRANSITION,
        status=RenderNodeStatus.READY,
        scene_number=_SCENE_NUMBER,
        clip_sequence_index=0,
        start_time_seconds=0.0,
        end_time_seconds=duration_seconds,
        duration_seconds=duration_seconds,
        payload={
            "status": "ready",
            "placement": "between_scenes",
            "direction": "between",
            "preset_id": "transition.cross_dissolve",
            "transition_type": "cross_dissolve",
            "source_scene_number": _SCENE_NUMBER,
            "target_scene_number": _SCENE_NUMBER,
            "source_clip_sequence_index": 0,
            "target_clip_sequence_index": 1,
            "source_track_index": 0,
            "target_track_index": 0,
            "start_time_seconds": 0.0,
            "end_time_seconds": duration_seconds,
            "duration_seconds": duration_seconds,
            "overlap_start_seconds": 0.0,
            "overlap_end_seconds": duration_seconds,
            "intensity": "medium",
            "requires_overlap": True,
            "implementation": {},
        },
    )


def test_split_scene_video_nodes_produce_distinct_labels_and_durations() -> None:
    """The core bug: scene_final_labels/scene_durations keyed on bare
    scene_number would have silently collided (the second sub-clip
    overwriting the first) or raised outright on the duplicate-key
    guard - both sub-clips must build their own real, distinct chain."""

    builder = FilterGraphBuilderService()

    video_nodes = [
        _video_node(clip_sequence_index=0, duration_seconds=8.0),
        _video_node(clip_sequence_index=1, duration_seconds=8.0),
    ]

    chains, warnings, operation_count, transition_count = builder._build_video_chains(
        video_nodes=video_nodes,
        scene_operation_nodes=[],
        transition_nodes=[_seam_transition_node()],
        width=1920,
        height=1080,
        frame_rate=30.0,
        pixel_format="yuv420p",
        capabilities=capabilities,
    )

    normalization_chains = [
        chain
        for chain in chains
        if chain.metadata.get("operation") == "scene_normalization"
    ]

    assert len(normalization_chains) == 2

    output_labels = {chain.output_label for chain in normalization_chains}

    assert output_labels == {
        "scene_9301_0_normalized",
        "scene_9301_1_normalized",
    }

    composition_chain = next(
        chain
        for chain in chains
        if chain.metadata.get("operation") == "video_composition"
    )

    assert composition_chain.metadata["scene_count"] == 2

    # A real crossfade, not a hard cut - the seam transition node above
    # must actually have been consumed.
    assert transition_count >= 1

    filter_names = [
        filter_node.filter_name for chain in chains for filter_node in chain.nodes
    ]

    assert "xfade" in filter_names


def test_split_scene_without_a_seam_transition_falls_back_to_a_hard_cut() -> None:
    """No transition node connecting the two sub-clips - a real gap,
    not a crash - must produce a deterministic concat/hard cut, the
    same fallback any other missing between-scene transition gets."""

    builder = FilterGraphBuilderService()

    video_nodes = [
        _video_node(clip_sequence_index=0, duration_seconds=8.0),
        _video_node(clip_sequence_index=1, duration_seconds=8.0),
    ]

    chains, warnings, operation_count, transition_count = builder._build_video_chains(
        video_nodes=video_nodes,
        scene_operation_nodes=[],
        transition_nodes=[],
        width=1920,
        height=1080,
        frame_rate=30.0,
        pixel_format="yuv420p",
        capabilities=capabilities,
    )

    composition_chain = next(
        chain
        for chain in chains
        if chain.metadata.get("operation") == "video_composition"
    )

    filter_names = [filter_node.filter_name for filter_node in composition_chain.nodes]

    assert "concat" in filter_names
    assert "xfade" not in filter_names


def test_duplicate_scene_and_clip_sequence_index_is_still_rejected() -> None:
    """The real, genuine duplicate case - the SAME sub-clip appearing
    twice - must still be rejected; only distinct clip_sequence_index
    values sharing a scene_number are legitimate."""

    builder = FilterGraphBuilderService()

    video_nodes = [
        _video_node(clip_sequence_index=0, duration_seconds=8.0),
        _video_node(clip_sequence_index=0, duration_seconds=8.0),
    ]

    try:
        builder._build_video_chains(
            video_nodes=video_nodes,
            scene_operation_nodes=[],
            transition_nodes=[],
            width=1920,
            height=1080,
            frame_rate=30.0,
            pixel_format="yuv420p",
            capabilities=capabilities,
        )
    except ValueError as error:
        assert "duplicate" in str(error).lower()
    else:
        raise AssertionError("Expected a ValueError for a genuine duplicate sub-clip.")
