"""
REQ-5 (genre-aware subtitle styling), 2026-09-22: locks in the two
real, previously-missing pieces this REQ built on top of the already-
live subtitle render path - (1) a genuinely distinct "bold_punchy"
subtitle preset for top10/reaction/comedy (larger, brighter, heavier
border - a real color/emphasis difference, not just a size bump), and
(2) a REAL alpha-keyframe fade for genres that set
animation_preset_id="animation.subtitle_fade" (horror, storytelling,
mystery, survival) - confirmed via code before this REQ that this
value was stored, validated, and threaded all the way to a FilterNode's
own metadata, but never actually produced any fade: `_translate_
subtitle()` only appended a warning string acknowledging the gap.
Every genre WITHOUT that animation preset must keep the exact original
hard pop on/off - zero regression for the 8 genres that never opted
into fading.
"""

from __future__ import annotations

import pytest

from src.models.ffmpeg_config import FFmpegCapabilities
from src.models.render_graph import RenderNode, RenderNodeStatus, RenderNodeType
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

_CAPABILITIES = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    filters={"drawtext"},
)


def _subtitle_node(
    *,
    preset_id: str,
    animation_preset_id: str | None,
    local_start: float = 1.0,
    local_end: float = 4.0,
) -> RenderNode:
    # scene_start_time_seconds is fixed at 0.0, so local offsets equal
    # the global start/end times exactly (a non-split scene).
    duration = local_end - local_start

    return RenderNode(
        node_type=RenderNodeType.SUBTITLE,
        status=RenderNodeStatus.READY,
        scene_number=1,
        start_time_seconds=local_start,
        end_time_seconds=local_end,
        duration_seconds=duration,
        payload={
            "scene_number": 1,
            "segment_index": 0,
            "text": "The bunker door opened.",
            "preset_id": preset_id,
            "animation_preset_id": animation_preset_id,
            "burn_into_video": True,
            "timing_source": "estimated",
            "start_time_seconds": local_start,
            "end_time_seconds": local_end,
            "duration_seconds": duration,
            "scene_start_time_seconds": 0.0,
            "scene_end_time_seconds": 8.0,
            "local_start_offset_seconds": local_start,
            "local_end_offset_seconds": local_end,
            "word_count": 4,
        },
    )


def test_bold_punchy_preset_is_a_real_distinct_treatment() -> None:
    style = VideoFilterTranslationService._subtitle_style("subtitle.bold_punchy")

    assert style["fontcolor"] == "yellow"
    assert int(style["fontsize"]) > 54  # larger than both existing presets
    assert int(style["borderw"]) > 3  # heavier than both existing presets


def test_default_and_cinematic_presets_are_unchanged() -> None:
    default_style = VideoFilterTranslationService._subtitle_style("subtitle.default")
    cinematic_style = VideoFilterTranslationService._subtitle_style(
        "subtitle.cinematic"
    )

    assert default_style["fontcolor"] == "white"
    assert default_style["fontsize"] == "48"
    assert cinematic_style["fontcolor"] == "white"
    assert cinematic_style["fontsize"] == "54"


def test_unknown_subtitle_preset_still_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported FFmpeg subtitle preset"):
        VideoFilterTranslationService._subtitle_style("subtitle.made_up")


def test_fade_animation_preset_adds_a_real_alpha_expression() -> None:
    service = VideoFilterTranslationService()

    node = _subtitle_node(
        preset_id="subtitle.cinematic",
        animation_preset_id="animation.subtitle_fade",
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

    options = translation.filters[0].options

    assert "alpha" in options
    assert "if(lt(t," in options["alpha"]
    assert not any("will be integrated" in warning for warning in translation.warnings)


def test_no_animation_preset_reproduces_the_exact_prior_hard_cut_behavior() -> None:
    """The other 8 registered genres never set animation_preset_id -
    real backward compatibility: no alpha key at all, same hard
    between(t,...) pop this render path has always used."""

    service = VideoFilterTranslationService()

    node = _subtitle_node(preset_id="subtitle.cinematic", animation_preset_id=None)

    translation = service.translate_scene_node(
        render_node=node,
        input_label="in",
        output_label="out",
        width=1920,
        height=1080,
        frame_rate=30.0,
        capabilities=_CAPABILITIES,
    )

    options = translation.filters[0].options

    assert "alpha" not in options
    assert "between(t" in options["enable"]


def test_unsupported_animation_preset_is_warned_about_not_silently_dropped() -> None:
    service = VideoFilterTranslationService()

    node = _subtitle_node(
        preset_id="subtitle.default",
        animation_preset_id="animation.made_up",
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

    assert "alpha" not in translation.filters[0].options
    assert any("animation.made_up" in warning for warning in translation.warnings)


def test_fade_duration_clamps_for_a_very_short_cue() -> None:
    """A cue shorter than 4x the default fade duration must still
    produce a valid, non-inverted fade rather than a nonsensical
    expression - fade duration shrinks with the cue instead."""

    service = VideoFilterTranslationService()

    node = _subtitle_node(
        preset_id="subtitle.cinematic",
        animation_preset_id="animation.subtitle_fade",
        local_start=1.0,
        local_end=1.1,  # 0.1s cue, shorter than the default 0.15s fade
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

    alpha = translation.filters[0].options["alpha"]

    # fade_seconds = 0.1 / 4 = 0.025, well-formed either way.
    assert "0.025" in alpha


def test_subtitle_fade_alpha_expression_math_at_a_normal_cue_length() -> None:
    expression = VideoFilterTranslationService._subtitle_fade_alpha_expression(
        local_start_seconds=1.0,
        local_end_seconds=4.0,
    )

    assert "1.15" in expression  # fade-in end: 1.0 + 0.15
    assert "3.85" in expression  # fade-out start: 4.0 - 0.15
