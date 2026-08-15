from __future__ import annotations

import pytest

from src.models.editorial_profile import FormatProfile
from src.services.format_profile_registry_service import (
    FormatProfileRegistryService,
)


def test_default_registry_contains_expected_formats() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    expected = {
        "format.narrative",
        "format.documentary",
        "format.investigation",
        "format.top10",
    }

    assert {profile.format_id for profile in registry.list_all()} == expected


def test_investigation_format_has_distinct_pacing_curve() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    investigation = registry.get("format.investigation")

    assert investigation.pacing_curve_override
    assert investigation.pacing_curve_override[-2].tension_level > (
        investigation.pacing_curve_override[0].tension_level
    )


def test_top10_format_has_higher_scene_density_multiplier() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    top10 = registry.get("format.top10")
    documentary = registry.get("format.documentary")

    assert top10.scene_density_multiplier > documentary.scene_density_multiplier


def test_resolve_falls_back_to_narrative_default() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    result = registry.resolve("format.unknown")

    assert result.is_resolved is True
    assert result.used_fallback is True
    assert result.resolved_format_id == "format.narrative"


def test_resolve_exact_match() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    result = registry.resolve("format.top10")

    assert result.found_exact_match is True
    assert result.used_fallback is False


def test_register_duplicate_without_replace_fails() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            FormatProfile(format_id="format.top10", display_name="Duplicate")
        )


def test_default_format_cannot_be_unregistered() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    with pytest.raises(ValueError, match="cannot be unregistered"):
        registry.unregister("format.narrative")


def test_unregister_unknown_format_raises_key_error() -> None:
    registry = FormatProfileRegistryService.with_default_profiles()

    with pytest.raises(KeyError):
        registry.unregister("format.unknown")
