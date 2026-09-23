"""
REQ-12 (top10 countdown rank cards), 2026-09-23: the corner badge
reuses the existing VISUAL_EFFECT node type by registering a new,
otherwise-ordinary preset (no color-grade implementation fields - the
real dynamic per-scene payload lives on EffectExecution.rank_badge_text
instead, per numeric_intensity_percent's own 3-layer pattern).
"""

from __future__ import annotations

from src.models.effect_registry import EffectCategory
from src.services.effect_registry_service import EffectRegistryService


def _registry() -> EffectRegistryService:
    return EffectRegistryService.with_default_presets()


def test_rank_badge_preset_is_registered() -> None:
    registry = _registry()

    assert registry.contains("visual.top10_rank_badge")


def test_rank_badge_preset_resolves_as_an_exact_match() -> None:
    registry = _registry()

    result = registry.resolve("visual.top10_rank_badge")

    assert result.found_exact_match is True
    assert result.used_fallback is False
    assert result.preset is not None
    assert result.preset.category == EffectCategory.VISUAL
    assert result.preset.implementation == {}


def test_rank_badge_preset_has_a_safe_fallback() -> None:
    registry = _registry()

    result = registry.resolve("visual.top10_rank_badge")

    assert result.preset is not None
    assert result.preset.fallback_preset_id == "visual.none"
