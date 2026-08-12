from __future__ import annotations

import pytest

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
    filters={"fade", "null"},
)


def _transition_node(
    *,
    placement: str,
    preset_id: str,
    transition_type: str,
    scene_number: int = 1,
    duration_seconds: float = 0.0,
) -> RenderNode:
    is_timeline_in = placement == "timeline_in"

    return RenderNode(
        node_type=RenderNodeType.TRANSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=duration_seconds,
        duration_seconds=duration_seconds,
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
            "end_time_seconds": duration_seconds,
            "duration_seconds": duration_seconds,
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


def test_unconsumed_non_cut_timeline_in_transition_is_rejected() -> None:
    """
    _validate_transition_consumption() itself still guards against a
    non-cut timeline-in/out transition that was never explicitly
    consumed - the real fade translation now happens earlier, in
    _apply_timeline_in_fade()/_finalize_video_output() (see below),
    which always marks the node consumed before this validation runs.
    This is the safety net for anything that skips that path.
    """

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


def test_unconsumed_non_cut_timeline_out_transition_is_rejected() -> None:
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


def test_apply_timeline_in_fade_translates_non_cut_preset() -> None:
    builder = FilterGraphBuilderService()

    node = _transition_node(
        placement="timeline_in",
        preset_id="transition.fade_black",
        transition_type="fade_black",
        duration_seconds=2.0,
    )

    consumed: set[str] = set()

    label, filters, warnings = builder._apply_timeline_in_fade(
        composed_label="video_scene_1",
        transition_nodes=[node],
        capabilities=capabilities,
        consumed_transition_ids=consumed,
    )

    assert label == "video_timeline_in"
    assert len(filters) == 1
    assert filters[0].filter_name == "fade"
    assert filters[0].options["t"] == "in"
    assert str(node.id) in consumed
    assert warnings == []


def test_apply_timeline_in_fade_skips_cut_preset() -> None:
    builder = FilterGraphBuilderService()

    node = _transition_node(
        placement="timeline_in",
        preset_id="transition.cut",
        transition_type="cut",
    )

    consumed: set[str] = set()

    label, filters, warnings = builder._apply_timeline_in_fade(
        composed_label="video_scene_1",
        transition_nodes=[node],
        capabilities=capabilities,
        consumed_transition_ids=consumed,
    )

    assert label == "video_scene_1"
    assert filters == []
    assert str(node.id) in consumed


def test_apply_timeline_in_fade_is_noop_without_a_node() -> None:
    builder = FilterGraphBuilderService()

    label, filters, warnings = builder._apply_timeline_in_fade(
        composed_label="video_scene_1",
        transition_nodes=[],
        capabilities=capabilities,
        consumed_transition_ids=set(),
    )

    assert label == "video_scene_1"
    assert filters == []


def test_finalize_video_output_applies_timeline_out_fade() -> None:
    builder = FilterGraphBuilderService()

    node = _transition_node(
        placement="timeline_out",
        preset_id="transition.fade_black",
        transition_type="fade_black",
        duration_seconds=2.0,
    )

    consumed: set[str] = set()

    filters, warnings = builder._finalize_video_output(
        composed_label="video_composed_2",
        composed_duration=20.0,
        transition_nodes=[node],
        capabilities=capabilities,
        consumed_transition_ids=consumed,
    )

    assert len(filters) == 1
    assert filters[0].filter_name == "fade"
    assert filters[0].options["t"] == "out"
    assert filters[0].options["st"] == "18"
    assert filters[0].output_labels == ["video_final"]
    assert str(node.id) in consumed


def test_finalize_video_output_falls_back_to_null_passthrough() -> None:
    builder = FilterGraphBuilderService()

    filters, warnings = builder._finalize_video_output(
        composed_label="video_composed_2",
        composed_duration=20.0,
        transition_nodes=[],
        capabilities=capabilities,
        consumed_transition_ids=set(),
    )

    assert len(filters) == 1
    assert filters[0].filter_name == "null"
    assert filters[0].output_labels == ["video_final"]


def test_finalize_video_output_skips_cut_timeline_out() -> None:
    builder = FilterGraphBuilderService()

    node = _transition_node(
        placement="timeline_out",
        preset_id="transition.cut",
        transition_type="cut",
    )

    consumed: set[str] = set()

    filters, warnings = builder._finalize_video_output(
        composed_label="video_composed_2",
        composed_duration=20.0,
        transition_nodes=[node],
        capabilities=capabilities,
        consumed_transition_ids=consumed,
    )

    assert len(filters) == 1
    assert filters[0].filter_name == "null"
    assert str(node.id) in consumed


def test_multiple_timeline_in_transitions_are_rejected() -> None:
    builder = FilterGraphBuilderService()

    first = _transition_node(
        placement="timeline_in",
        preset_id="transition.fade_black",
        transition_type="fade_black",
        duration_seconds=1.0,
    )
    second = _transition_node(
        placement="timeline_in",
        preset_id="transition.cross_dissolve",
        transition_type="cross_dissolve",
        duration_seconds=1.0,
    )

    with pytest.raises(ValueError, match="Multiple"):
        builder._apply_timeline_in_fade(
            composed_label="video_scene_1",
            transition_nodes=[first, second],
            capabilities=capabilities,
            consumed_transition_ids=set(),
        )
