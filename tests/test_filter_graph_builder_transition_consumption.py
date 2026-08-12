from __future__ import annotations

import pytest

from src.models.render_graph import (
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.filter_graph_builder_service import (
    FilterGraphBuilderService,
)


def _transition_node(
    *,
    placement: str,
    preset_id: str,
    transition_type: str,
    scene_number: int = 1,
) -> RenderNode:
    is_timeline_in = placement == "timeline_in"

    return RenderNode(
        node_type=RenderNodeType.TRANSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=0.0,
        duration_seconds=0.0,
        payload={
            "status": "ready",
            "placement": placement,
            "direction": ("in" if is_timeline_in else "out"),
            "preset_id": preset_id,
            "transition_type": transition_type,
            "source_scene_number": (None if is_timeline_in else scene_number),
            "target_scene_number": (scene_number if is_timeline_in else None),
            "source_track_index": (None if is_timeline_in else 0),
            "target_track_index": (0 if is_timeline_in else None),
            "start_time_seconds": 0.0,
            "end_time_seconds": 0.0,
            "duration_seconds": 0.0,
            "overlap_start_seconds": None,
            "overlap_end_seconds": None,
            "intensity": "medium",
            "requires_overlap": False,
            "implementation": {},
        },
    )


def test_cut_timeline_in_transition_needs_no_translation() -> None:
    """
    Regression test: a cut timeline-in/out transition needs no FFmpeg
    filter (the video just starts/ends with no effect) - it must not
    be rejected the way a real, untranslated fade/dissolve preset is.
    A real end-to-end render hit this exact case (genre.default's
    transition_in_preset_id/transition_out_preset_id both default to
    transition.cut) and failed before this fix.
    """

    node = _transition_node(
        placement="timeline_in",
        preset_id="transition.cut",
        transition_type="cut",
    )

    FilterGraphBuilderService._validate_transition_consumption(
        transition_nodes=[node],
        consumed_transition_ids=set(),
    )


def test_cut_timeline_out_transition_needs_no_translation() -> None:
    node = _transition_node(
        placement="timeline_out",
        preset_id="transition.cut",
        transition_type="cut",
    )

    FilterGraphBuilderService._validate_transition_consumption(
        transition_nodes=[node],
        consumed_transition_ids=set(),
    )


def test_non_cut_timeline_in_transition_is_still_rejected() -> None:
    node = _transition_node(
        placement="timeline_in",
        preset_id="transition.fade_black",
        transition_type="fade_black",
    )

    with pytest.raises(ValueError, match="Timeline-in transition"):
        FilterGraphBuilderService._validate_transition_consumption(
            transition_nodes=[node],
            consumed_transition_ids=set(),
        )


def test_non_cut_timeline_out_transition_is_still_rejected() -> None:
    node = _transition_node(
        placement="timeline_out",
        preset_id="transition.cross_dissolve",
        transition_type="cross_dissolve",
    )

    with pytest.raises(ValueError, match="Timeline-out transition"):
        FilterGraphBuilderService._validate_transition_consumption(
            transition_nodes=[node],
            consumed_transition_ids=set(),
        )
