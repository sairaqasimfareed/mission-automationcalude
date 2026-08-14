from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
)
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
    filters={
        "zoompan",
        "eq",
        "colorbalance",
        "vignette",
        "drawtext",
        "xfade",
        "concat",
        "null",
        "colorchannelmixer",
        "noise",
    },
)

service = (
    VideoFilterTranslationService()
)


camera_node = RenderNode(
    node_type=RenderNodeType.CAMERA,
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "scene_number": 1,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": "camera.slow_zoom_in",
        "motion_type": "zoom",
        "direction": "in",
        "intensity": "medium",
        "start_time_seconds": 0.0,
        "end_time_seconds": 8.0,
        "duration_seconds": 8.0,
        "scene_start_time_seconds": 0.0,
        "scene_end_time_seconds": 8.0,
        "scene_duration_seconds": 8.0,
        "local_start_offset_seconds": 0.0,
        "local_end_offset_seconds": 8.0,
        "zoom_start": 1.0,
        "zoom_end": 1.08,
        "implementation": {
            "motion": "zoom",
            "direction": "in",
            "default_start_scale": 1.0,
            "default_end_scale": 1.08,
        },
    },
)

camera_translation = (
    service.translate_scene_node(
        render_node=camera_node,
        input_label="scene_1_base",
        output_label="scene_1_camera",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
)

assert camera_translation.skipped is False
assert camera_translation.filter_count == 1

assert (
    camera_translation
    .filters[0]
    .filter_name
    == "zoompan"
)

assert (
    "[scene_1_camera]"
    in camera_translation
    .filters[0]
    .render_expression()
)


effect_node = RenderNode(
    node_type=(
        RenderNodeType.VISUAL_EFFECT
    ),
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "scene_number": 1,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": (
            "visual.horror_dark_grade"
        ),
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
        "implementation": {
            "brightness": -0.08,
            "contrast": 1.12,
            "saturation": 0.78,
            "temperature": "cool",
        },
    },
)

effect_translation = (
    service.translate_scene_node(
        render_node=effect_node,
        input_label="scene_1_camera",
        output_label="scene_1_grade",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
)

assert effect_translation.filter_count == 2

assert (
    effect_translation
    .filters[0]
    .filter_name
    == "eq"
)

assert (
    effect_translation
    .filters[1]
    .filter_name
    == "colorbalance"
)


vignette_node = RenderNode(
    node_type=(
        RenderNodeType.VISUAL_EFFECT
    ),
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "scene_number": 1,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": (
            "visual.vignette_soft"
        ),
        "effect_type": "vignette",
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
        "implementation": {
            "effect": "vignette",
            "strength": 0.25,
        },
    },
)

vignette_translation = (
    service.translate_scene_node(
        render_node=vignette_node,
        input_label="scene_1_grade",
        output_label="scene_1_vignette",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
)

assert (
    vignette_translation
    .filters[0]
    .filter_name
    == "vignette"
)


subtitle_node = RenderNode(
    node_type=RenderNodeType.SUBTITLE,
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=1.0,
    end_time_seconds=4.0,
    duration_seconds=3.0,
    payload={
        "scene_number": 1,
        "segment_index": 0,
        "text": (
            "The bunker door opened."
        ),
        "preset_id": (
            "subtitle.cinematic"
        ),
        "animation_preset_id": None,
        "burn_into_video": True,
        "timing_source": "estimated",
        "start_time_seconds": 1.0,
        "end_time_seconds": 4.0,
        "duration_seconds": 3.0,
        "scene_start_time_seconds": 0.0,
        "scene_end_time_seconds": 8.0,
        "local_start_offset_seconds": 1.0,
        "local_end_offset_seconds": 4.0,
        "word_count": 4,
    },
)

subtitle_translation = (
    service.translate_scene_node(
        render_node=subtitle_node,
        input_label="scene_1_vignette",
        output_label="scene_1_subtitle",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
)

assert (
    subtitle_translation
    .filters[0]
    .filter_name
    == "drawtext"
)

subtitle_expression = (
    subtitle_translation
    .filters[0]
    .render_expression()
)

assert "between(t" in (
    subtitle_expression
)

assert "The bunker door opened." in (
    subtitle_expression
)


animation_node = RenderNode(
    node_type=RenderNodeType.ANIMATION,
    status=RenderNodeStatus.READY,
    scene_number=2,
    start_time_seconds=8.0,
    end_time_seconds=15.0,
    duration_seconds=7.0,
    payload={
        "scene_number": 2,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": (
            "animation.slow_parallax"
        ),
        "animation_type": "parallax",
        "target": None,
        "intensity": "medium",
        "start_time_seconds": 8.0,
        "end_time_seconds": 15.0,
        "duration_seconds": 7.0,
        "scene_start_time_seconds": 8.0,
        "scene_end_time_seconds": 15.0,
        "scene_duration_seconds": 7.0,
        "local_start_offset_seconds": 0.0,
        "local_end_offset_seconds": 7.0,
        "implementation": {
            "animation": "parallax",
            "speed": "slow",
        },
    },
)

animation_translation = (
    service.translate_scene_node(
        render_node=animation_node,
        input_label="scene_2_base",
        output_label="scene_2_animation",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
)

assert (
    animation_translation
    .filters[0]
    .filter_name
    == "zoompan"
)

assert animation_translation.warnings


transition_node = RenderNode(
    node_type=RenderNodeType.TRANSITION,
    status=RenderNodeStatus.READY,
    start_time_seconds=7.4,
    end_time_seconds=8.0,
    duration_seconds=0.6,
    payload={
        "status": "ready",
        "placement": "between_scenes",
        "direction": "between",
        "preset_id": (
            "transition.cross_dissolve"
        ),
        "transition_type": (
            "cross_dissolve"
        ),
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
            "type": (
                "cross_dissolve"
            ),
            "default_duration_seconds": 0.6,
        },
    },
)

transition_translation = (
    service.translate_transition(
        render_node=transition_node,
        source_label="scene_1_final",
        target_label="scene_2_final",
        output_label="transition_1_2",
        offset_seconds=7.4,
        capabilities=capabilities,
    )
)

assert (
    transition_translation
    .filters[0]
    .filter_name
    == "xfade"
)

transition_expression = (
    transition_translation
    .filters[0]
    .render_expression()
)

assert "transition=fade" in (
    transition_expression
)

assert "duration=0.6" in (
    transition_expression
)

assert "offset=7.4" in (
    transition_expression
)


unsupported_node = (
    camera_node.model_copy(
        deep=True
    )
)

unsupported_payload = dict(
    unsupported_node.payload
)

unsupported_payload[
    "motion_type"
] = "orbit"

unsupported_payload[
    "preset_id"
] = "camera.orbit"

unsupported_node.payload = (
    unsupported_payload
)

try:
    service.translate_scene_node(
        render_node=unsupported_node,
        input_label="source",
        output_label="target",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
except ValueError:
    print(
        "Unsupported camera motion "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Unsupported camera motion "
        "should fail."
    )


def _camera_payload(*, preset_id, motion_type, direction):
    return {
        "scene_number": 1,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": preset_id,
        "motion_type": motion_type,
        "direction": direction,
        "intensity": "medium",
        "start_time_seconds": 0.0,
        "end_time_seconds": 4.0,
        "duration_seconds": 4.0,
        "scene_start_time_seconds": 0.0,
        "scene_end_time_seconds": 4.0,
        "scene_duration_seconds": 4.0,
        "local_start_offset_seconds": 0.0,
        "local_end_offset_seconds": 4.0,
        "zoom_start": None,
        "zoom_end": None,
        "implementation": {
            "motion": motion_type,
            "direction": direction,
        },
    }


pan_left_node = RenderNode(
    node_type=RenderNodeType.CAMERA,
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=0.0,
    end_time_seconds=4.0,
    duration_seconds=4.0,
    payload=_camera_payload(
        preset_id="camera.pan_left",
        motion_type="pan",
        direction="left",
    ),
)

pan_left_translation = service.translate_scene_node(
    render_node=pan_left_node,
    input_label="scene_1_base",
    output_label="scene_1_pan",
    width=1920,
    height=1080,
    frame_rate=30.0,
    capabilities=capabilities,
)

assert pan_left_translation.filters[0].filter_name == "zoompan"
assert pan_left_translation.filters[0].options["z"] == "1.15"


for direction in ["left", "right", "up", "down"]:
    directional_node = RenderNode(
        node_type=RenderNodeType.CAMERA,
        status=RenderNodeStatus.READY,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=4.0,
        duration_seconds=4.0,
        payload=_camera_payload(
            preset_id=f"camera.pan_{direction}",
            motion_type="pan",
            direction=direction,
        ),
    )

    directional_translation = service.translate_scene_node(
        render_node=directional_node,
        input_label="scene_1_base",
        output_label="scene_1_pan",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )

    assert directional_translation.filters[0].filter_name == "zoompan"


def _visual_payload(preset_id):
    return {
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
        "implementation": {},
    }


expected_visual_filters = {
    "visual.grayscale": ["eq", "null"],
    "visual.sepia_tone": ["colorchannelmixer"],
    "visual.high_contrast_punch": ["eq", "null"],
    "visual.film_grain_light": ["noise"],
    "visual.cool_blue_grade": ["eq", "colorbalance"],
    "visual.lut_teal_orange": ["eq", "colorbalance"],
    "visual.lut_bleach_bypass": ["eq", "null"],
    "visual.lut_kodak_warm": ["eq", "colorbalance"],
    "visual.lut_moody_desaturated": ["eq", "colorbalance"],
    "visual.lut_vibrant_punch": ["eq", "null"],
}

for preset_id, expected_filters in expected_visual_filters.items():
    visual_node = RenderNode(
        node_type=RenderNodeType.VISUAL_EFFECT,
        status=RenderNodeStatus.READY,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload=_visual_payload(preset_id),
    )

    visual_translation = service.translate_scene_node(
        render_node=visual_node,
        input_label="scene_1_camera",
        output_label="scene_1_grade",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )

    actual_filters = [
        filter_node.filter_name
        for filter_node in visual_translation.filters
    ]

    assert actual_filters == expected_filters, (
        f"{preset_id}: expected {expected_filters}, got {actual_filters}"
    )


def _animation_payload(preset_id):
    return {
        "scene_number": 2,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": preset_id,
        "animation_type": "parallax",
        "target": None,
        "intensity": "medium",
        "start_time_seconds": 8.0,
        "end_time_seconds": 15.0,
        "duration_seconds": 7.0,
        "scene_start_time_seconds": 8.0,
        "scene_end_time_seconds": 15.0,
        "scene_duration_seconds": 7.0,
        "local_start_offset_seconds": 0.0,
        "local_end_offset_seconds": 7.0,
        "implementation": {},
    }


for preset_id in [
    "animation.slow_parallax_reverse",
    "animation.slow_pan_vertical",
    "animation.gentle_zoom_pulse",
]:
    new_animation_node = RenderNode(
        node_type=RenderNodeType.ANIMATION,
        status=RenderNodeStatus.READY,
        scene_number=2,
        start_time_seconds=8.0,
        end_time_seconds=15.0,
        duration_seconds=7.0,
        payload=_animation_payload(preset_id),
    )

    new_animation_translation = service.translate_scene_node(
        render_node=new_animation_node,
        input_label="scene_2_base",
        output_label="scene_2_animation",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )

    assert (
        new_animation_translation.filters[0].filter_name
        == "zoompan"
    )
    assert new_animation_translation.warnings


unknown_animation_node = animation_node.model_copy(deep=True)

unknown_animation_payload = dict(unknown_animation_node.payload)
unknown_animation_payload["preset_id"] = "animation.orbit_bounce"
unknown_animation_node.payload = unknown_animation_payload

try:
    service.translate_scene_node(
        render_node=unknown_animation_node,
        input_label="source",
        output_label="target",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=capabilities,
    )
except ValueError:
    print("Unsupported animation preset successfully blocked.")
else:
    raise AssertionError(
        "Unsupported animation preset should fail."
    )


for transition_type, expected_xfade_name in [
    ("wipe_left", "wipeleft"),
    ("wipe_right", "wiperight"),
    ("slide_left", "slideleft"),
    ("circle_crop", "circlecrop"),
    ("pixelize", "pixelize"),
]:
    new_transition_node = RenderNode(
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

    new_transition_translation = service.translate_transition(
        render_node=new_transition_node,
        source_label="scene_1_final",
        target_label="scene_2_final",
        output_label="transition_1_2",
        offset_seconds=7.4,
        capabilities=capabilities,
    )

    new_transition_expression = (
        new_transition_translation.filters[0].render_expression()
    )

    assert (
        f"transition={expected_xfade_name}" in new_transition_expression
    )


print(
    "Video Filter Translation Service tests "
    "completed successfully."
)