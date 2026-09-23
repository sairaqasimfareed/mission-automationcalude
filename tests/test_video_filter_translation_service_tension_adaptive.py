"""
REQ-1/2 (tension-adaptive film grain/vignette), 2026-09-22: before this,
neither preset actually varied at all - film_grain used a hardcoded
noise alls=12 regardless of any intensity, and vignette_soft read a
"strength" value that was stored in metadata but never applied to the
real FFmpeg vignette filter at all. This file locks in the fix: a real
EffectExecution.numeric_intensity_percent now produces a real, varying
FFmpeg parameter, and None (no genre range configured) reproduces the
exact previous hardcoded output - a scene/genre that predates this
feature must render identically to before.
"""

from __future__ import annotations

from src.models.ffmpeg_config import FFmpegCapabilities
from src.models.render_graph import (
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

_CAPABILITIES = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    filters={"vignette", "noise", "null"},
)


def _visual_effect_node(
    *, preset_id: str, numeric_intensity_percent: int | None
) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.VISUAL_EFFECT,
        status=RenderNodeStatus.READY,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={
            "scene_number": 1,
            "track_index": 0,
            "layer_index": 0,
            "preset_id": preset_id,
            "effect_type": "visual",
            "timing_mode": "full_scene",
            "intensity": "medium",
            "numeric_intensity_percent": numeric_intensity_percent,
            "start_time_seconds": 0.0,
            "end_time_seconds": 8.0,
            "duration_seconds": 8.0,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 8.0,
            "scene_duration_seconds": 8.0,
            "local_start_offset_seconds": 0.0,
            "relative_position_percent": None,
            "implementation": (
                {"effect": "vignette", "strength": 0.25}
                if preset_id == "visual.vignette_soft"
                else {"filter": "film_grain_light"}
            ),
        },
    )


def test_film_grain_with_no_numeric_intensity_reproduces_old_hardcoded_value() -> None:
    """A scene/genre that predates this feature (no numeric_intensity_
    percent resolved) must render identically to before - alls=12."""

    service = VideoFilterTranslationService()

    node = _visual_effect_node(
        preset_id="visual.film_grain_light", numeric_intensity_percent=None
    )

    translation = service.translate_scene_node(
        render_node=node,
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    assert translation.filters[0].options["alls"] == "12"


def test_film_grain_intensity_scales_the_real_noise_level() -> None:
    service = VideoFilterTranslationService()

    low = service.translate_scene_node(
        render_node=_visual_effect_node(
            preset_id="visual.film_grain_light", numeric_intensity_percent=0
        ),
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    high = service.translate_scene_node(
        render_node=_visual_effect_node(
            preset_id="visual.film_grain_light", numeric_intensity_percent=100
        ),
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    low_alls = int(low.filters[0].options["alls"])
    high_alls = int(high.filters[0].options["alls"])

    assert low_alls < high_alls
    assert low_alls >= 0


def test_vignette_with_no_numeric_intensity_reproduces_old_hardcoded_angle() -> None:
    service = VideoFilterTranslationService()

    node = _visual_effect_node(
        preset_id="visual.vignette_soft", numeric_intensity_percent=None
    )

    translation = service.translate_scene_node(
        render_node=node,
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    assert translation.filters[0].options["angle"] == "PI/4"


def test_vignette_intensity_scales_the_real_angle_stronger_at_higher_intensity() -> (
    None
):
    """FFmpeg's real vignette filter gets STRONGER as angle gets
    LARGER (confirmed against real ffmpeg output - see
    test_video_filter_translation_service_real_ffmpeg.py) - confirms
    the direction is right, not just "some number changed"."""

    service = VideoFilterTranslationService()

    low = service.translate_scene_node(
        render_node=_visual_effect_node(
            preset_id="visual.vignette_soft", numeric_intensity_percent=0
        ),
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    high = service.translate_scene_node(
        render_node=_visual_effect_node(
            preset_id="visual.vignette_soft", numeric_intensity_percent=100
        ),
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    low_angle = float(low.filters[0].options["angle"])
    high_angle = float(high.filters[0].options["angle"])

    # Higher intensity -> larger angle -> a real, stronger vignette.
    assert high_angle > low_angle
    assert low_angle > 0.0
