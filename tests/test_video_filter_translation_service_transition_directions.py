"""
REQ-6 (transition variety), 2026-09-22: locks in the real gap this REQ
actually found (memory's own original "only cross_dissolve exists"
claim was stale - 8 real transitions already worked end to end before
this REQ) - FFmpeg's xfade filter natively supports wipe/slide in all
four directions, but only wipe_left/wipe_right/slide_left were ever
registered as real, selectable transition.* presets. Adds wipe_up,
wipe_down, slide_right, slide_up, slide_down. "push" deliberately
skipped - confirmed against FFmpeg's real xfade option list, there is
no push-named transition; what editors brand as "push" is mechanically
identical to the already-existing slide.
"""

from __future__ import annotations

from src.models.ffmpeg_config import FFmpegCapabilities
from src.models.render_graph import RenderNode, RenderNodeStatus, RenderNodeType
from src.services.effect_registry_service import EffectRegistryService
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

_CAPABILITIES = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    filters={"xfade", "concat"},
)

_NEW_DIRECTIONS = {
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "slide_right": "slideright",
    "slide_up": "slideup",
    "slide_down": "slidedown",
}


def test_every_new_direction_maps_to_the_real_xfade_option_name() -> None:
    for transition_type, expected_xfade_name in _NEW_DIRECTIONS.items():
        assert (
            VideoFilterTranslationService._xfade_transition_name(transition_type)
            == expected_xfade_name
        )


def test_every_new_transition_preset_is_registered_and_resolves() -> None:
    registry = EffectRegistryService.with_default_presets()

    for transition_type in _NEW_DIRECTIONS:
        preset_id = f"transition.{transition_type}"

        assert registry.contains(preset_id), f"Expected registered preset: {preset_id}"

        result = registry.resolve(preset_id)

        assert result.is_resolved is True
        assert result.found_exact_match is True
        assert result.preset is not None
        assert result.preset.implementation["type"] == transition_type


def test_push_was_deliberately_not_registered() -> None:
    registry = EffectRegistryService.with_default_presets()

    assert not registry.contains("transition.push_left")
    assert not registry.contains("transition.push_right")
    assert not registry.contains("transition.push")


def _transition_node(*, transition_type: str) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.TRANSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=7.4,
        end_time_seconds=8.0,
        duration_seconds=0.6,
        payload={
            "status": "ready",
            "placement": "between_scenes",
            "direction": "between",
            "preset_id": f"transition.{transition_type}",
            "transition_type": transition_type,
            "source_scene_number": 1,
            "target_scene_number": 2,
            "source_track_index": 0,
            "target_track_index": 0,
            "start_time_seconds": 7.4,
            "end_time_seconds": 8.0,
            "duration_seconds": 0.6,
            "overlap_start_seconds": 7.4,
            "overlap_end_seconds": 8.0,
            "intensity": "medium",
            "requires_overlap": True,
            "implementation": {
                "type": transition_type,
                "default_duration_seconds": 0.6,
            },
        },
    )


def test_translate_transition_builds_a_real_xfade_filter_for_each_new_direction() -> (
    None
):
    service = VideoFilterTranslationService()

    for transition_type, expected_xfade_name in _NEW_DIRECTIONS.items():
        translation = service.translate_transition(
            render_node=_transition_node(transition_type=transition_type),
            source_label="scene_1_final",
            target_label="scene_2_final",
            output_label="transition_1_2",
            offset_seconds=7.4,
            capabilities=_CAPABILITIES,
        )

        assert translation.filters[0].filter_name == "xfade"

        expression = translation.filters[0].render_expression()

        assert f"transition={expected_xfade_name}" in expression
        assert "duration=0.6" in expression
