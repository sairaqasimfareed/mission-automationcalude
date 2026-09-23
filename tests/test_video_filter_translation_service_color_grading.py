"""
REQ-11 (genre-adaptive color grading), 2026-09-22: locks in the two
new parametric grade presets and the real per-genre reassignment this
REQ found was necessary - genre.medical's own previous grade
(visual.cool_blue_grade) actually contradicted this REQ's locked
design (a real cool/blue tint, not "clean and neutral"); genre.travel's
own previous grade (visual.lut_vibrant_punch) was vibrant but had no
warm color push at all, despite the locked design specifically wanting
"vibrant, warm, golden-hour" for travel.
"""

from __future__ import annotations

from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)


def test_golden_hour_warm_pushes_toward_warm_and_away_from_blue() -> None:
    spec = VideoFilterTranslationService._PARAMETRIC_GRADE_PRESETS[
        "visual.golden_hour_warm"
    ]

    assert spec.brightness > 0
    assert spec.saturation > 1.0  # vibrant
    assert spec.color_balance is not None
    assert float(spec.color_balance["rs"]) > 0  # warm red push in shadows
    assert float(spec.color_balance["rm"]) > 0  # warm red push in midtones
    assert float(spec.color_balance["bs"]) < 0  # blue pulled down in shadows


def test_clean_neutral_has_no_color_cast_at_all() -> None:
    spec = VideoFilterTranslationService._PARAMETRIC_GRADE_PRESETS[
        "visual.clean_neutral"
    ]

    assert spec.color_balance is None  # genuinely neutral - no tint
    assert spec.saturation <= 1.0  # not vibrant, reads clean/clinical


def test_clean_neutral_is_a_real_different_direction_than_the_cool_grade_it_replaced() -> (
    None
):
    cool_blue = VideoFilterTranslationService._PARAMETRIC_GRADE_PRESETS[
        "visual.cool_blue_grade"
    ]
    clean_neutral = VideoFilterTranslationService._PARAMETRIC_GRADE_PRESETS[
        "visual.clean_neutral"
    ]

    assert cool_blue.color_balance is not None
    assert clean_neutral.color_balance is None


def test_new_presets_are_registered_and_resolve() -> None:
    registry = EffectRegistryService.with_default_presets()

    for preset_id in ("visual.golden_hour_warm", "visual.clean_neutral"):
        assert registry.contains(preset_id), f"Expected registered preset: {preset_id}"

        result = registry.resolve(preset_id)

        assert result.is_resolved is True
        assert result.found_exact_match is True


def test_travel_and_medical_reference_the_new_presets() -> None:
    registry = GenreProfileRegistryService.with_default_profiles()

    travel = registry.resolve("genre.travel").profile
    medical = registry.resolve("genre.medical").profile

    assert travel is not None
    assert medical is not None

    assert travel.editing.visual_preset_ids == ["visual.golden_hour_warm"]
    assert medical.editing.visual_preset_ids == ["visual.clean_neutral"]

    # The two presets these replaced must no longer be referenced by
    # any genre this REQ was scoped to fix.
    assert "visual.cool_blue_grade" not in medical.editing.visual_preset_ids
    assert "visual.lut_vibrant_punch" not in travel.editing.visual_preset_ids


def test_top10_is_left_unchanged() -> None:
    """top10's own visual.high_contrast_punch already reasonably
    matches "punchy and saturated" - this REQ deliberately did not
    touch it."""

    registry = GenreProfileRegistryService.with_default_profiles()

    top10 = registry.resolve("genre.top10").profile

    assert top10 is not None
    assert top10.editing.visual_preset_ids == ["visual.high_contrast_punch"]
