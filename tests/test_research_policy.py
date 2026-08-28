from __future__ import annotations

from src.models.genre_profile import ResearchPolicy


def test_phase_7_fields_default_to_empty() -> None:
    policy = ResearchPolicy()

    assert policy.preferred_source_types == []
    assert policy.excluded_sources == []
    assert policy.freshness_requirement is None
    assert policy.geographic_scope is None


def test_phase_7_fields_can_be_set() -> None:
    policy = ResearchPolicy(
        preferred_source_types=["primary documents", "academic papers"],
        excluded_sources=["unverified forums"],
        freshness_requirement="Prefer sources from the last 5 years",
        geographic_scope="North Atlantic maritime records",
    )

    assert policy.preferred_source_types == ["primary documents", "academic papers"]
    assert policy.excluded_sources == ["unverified forums"]
    assert policy.freshness_requirement == "Prefer sources from the last 5 years"


def test_source_lists_strip_whitespace_and_drop_blank_entries() -> None:
    policy = ResearchPolicy(
        preferred_source_types=["  academic papers  ", "", "   "],
        excluded_sources=["  unverified forums  ", ""],
    )

    assert policy.preferred_source_types == ["academic papers"]
    assert policy.excluded_sources == ["unverified forums"]


def test_optional_policy_text_normalizes_blank_strings_to_none() -> None:
    policy = ResearchPolicy(freshness_requirement="   ", geographic_scope="")

    assert policy.freshness_requirement is None
    assert policy.geographic_scope is None


def test_backward_compatible_round_trip_without_phase_7_fields() -> None:
    policy = ResearchPolicy()
    raw = policy.model_dump_json()

    reloaded = ResearchPolicy.model_validate_json(raw)

    assert reloaded.preferred_source_types == []
    assert reloaded.geographic_scope is None
