from __future__ import annotations

import pytest

from src.models.ffmpeg_config import FFmpegCapabilities
from src.models.render_graph import (
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

capabilities = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    filters={"fade"},
)

service = VideoFilterTranslationService()


def _timeline_node(
    *,
    placement: str,
    preset_id: str,
    transition_type: str,
    duration_seconds: float = 2.0,
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
            "source_scene_number": (None if is_timeline_in else 1),
            "target_scene_number": (1 if is_timeline_in else None),
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


def test_timeline_in_produces_fade_in_filter() -> None:
    node = _timeline_node(
        placement="timeline_in",
        preset_id="transition.fade_black",
        transition_type="fade_black",
    )

    translation = service.translate_timeline_fade(
        render_node=node,
        input_label="video_scene_1",
        output_label="video_timeline_in",
        fade_start_seconds=0.0,
        capabilities=capabilities,
    )

    assert len(translation.filters) == 1

    filter_node = translation.filters[0]

    assert filter_node.filter_name == "fade"
    assert filter_node.options["t"] == "in"
    assert filter_node.options["st"] == "0"
    assert filter_node.options["d"] == "2"
    assert filter_node.options["color"] == "black"
    assert translation.output_label == "video_timeline_in"
    assert translation.skipped is False


def test_timeline_out_produces_fade_out_filter() -> None:
    node = _timeline_node(
        placement="timeline_out",
        preset_id="transition.fade_black",
        transition_type="fade_black",
        duration_seconds=1.5,
    )

    translation = service.translate_timeline_fade(
        render_node=node,
        input_label="video_composed_3",
        output_label="video_final",
        fade_start_seconds=18.5,
        capabilities=capabilities,
    )

    filter_node = translation.filters[0]

    assert filter_node.filter_name == "fade"
    assert filter_node.options["t"] == "out"
    assert filter_node.options["st"] == "18.5"
    assert filter_node.options["d"] == "1.5"


def test_cross_dissolve_degrades_to_black_fade_with_warning() -> None:
    node = _timeline_node(
        placement="timeline_in",
        preset_id="transition.cross_dissolve",
        transition_type="cross_dissolve",
    )

    translation = service.translate_timeline_fade(
        render_node=node,
        input_label="video_scene_1",
        output_label="video_timeline_in",
        fade_start_seconds=0.0,
        capabilities=capabilities,
    )

    assert translation.filters[0].filter_name == "fade"
    assert any("cross_dissolve" in warning for warning in translation.warnings)


def test_rejects_between_scenes_placement() -> None:
    node = RenderNode(
        node_type=RenderNodeType.TRANSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=2.0,
        duration_seconds=2.0,
        payload={
            "status": "ready",
            "placement": "between_scenes",
            "direction": "between",
            "preset_id": "transition.cross_dissolve",
            "transition_type": "cross_dissolve",
            "source_scene_number": 1,
            "target_scene_number": 2,
            "source_track_index": 0,
            "target_track_index": 0,
            "start_time_seconds": 0.0,
            "end_time_seconds": 2.0,
            "duration_seconds": 2.0,
            "overlap_start_seconds": None,
            "overlap_end_seconds": None,
            "intensity": "medium",
            "requires_overlap": False,
            "implementation": {},
        },
    )

    with pytest.raises(ValueError, match="timeline-in or timeline-out"):
        service.translate_timeline_fade(
            render_node=node,
            input_label="video_scene_1",
            output_label="video_out",
            fade_start_seconds=0.0,
            capabilities=capabilities,
        )


def test_rejects_negative_fade_start() -> None:
    node = _timeline_node(
        placement="timeline_out",
        preset_id="transition.fade_black",
        transition_type="fade_black",
    )

    with pytest.raises(ValueError, match="cannot be negative"):
        service.translate_timeline_fade(
            render_node=node,
            input_label="video_composed_1",
            output_label="video_final",
            fade_start_seconds=-1.0,
            capabilities=capabilities,
        )


def test_rejects_zero_duration() -> None:
    node = _timeline_node(
        placement="timeline_in",
        preset_id="transition.fade_black",
        transition_type="fade_black",
        duration_seconds=0.0,
    )

    with pytest.raises(ValueError, match="positive duration"):
        service.translate_timeline_fade(
            render_node=node,
            input_label="video_scene_1",
            output_label="video_timeline_in",
            fade_start_seconds=0.0,
            capabilities=capabilities,
        )
