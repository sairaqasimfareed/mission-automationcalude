from __future__ import annotations

from src.models.editorial_critique import (
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
)
from src.models.editorial_profile import EditorialProfile
from src.models.script_quality_report import ScriptQualityStatus
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.script_quality_gate_service import ScriptQualityGateService

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _mystery_profile() -> EditorialProfile:
    # quality_thresholds: factual_confidence=55, retention_architecture=60,
    # hook_strength=55.
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.mystery")
    )


def _finding(**overrides: object) -> CriticFinding:
    base: dict[str, object] = dict(
        dimension="narrative_coherence",
        severity=FindingSeverity.MINOR,
        segment_number=None,
        problem="Minor wording issue.",
        reason="Reads slightly awkward.",
        recommended_correction="Rephrase for flow.",
    )
    base.update(overrides)
    return CriticFinding(**base)


def _critique(**overrides: object) -> EditorialCritique:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        dimension_scores={
            "factual_confidence": 80,
            "retention_architecture": 80,
            "hook_strength": 80,
        },
        findings=[],
        prompt_version="editorial_critique_prompt_v1.0.0",
    )
    base.update(overrides)
    return EditorialCritique(**base)


def test_all_scores_above_threshold_with_no_findings_approves() -> None:
    service = ScriptQualityGateService()

    report = service.evaluate(
        critique=_critique(), editorial_profile=_mystery_profile()
    )

    assert report.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION
    assert report.passed is True
    assert report.failed_dimensions == []


def test_a_score_below_threshold_forces_needs_revision() -> None:
    critique = _critique(
        dimension_scores={
            "factual_confidence": 40,
            "retention_architecture": 80,
            "hook_strength": 80,
        }
    )

    service = ScriptQualityGateService()

    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    assert report.status == ScriptQualityStatus.NEEDS_REVISION
    assert "factual_confidence" in report.failed_dimensions


def test_a_blocking_finding_forces_needs_revision_even_with_high_scores() -> None:
    critique = _critique(findings=[_finding(severity=FindingSeverity.BLOCKING)])

    service = ScriptQualityGateService()

    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    assert report.status == ScriptQualityStatus.NEEDS_REVISION
    assert report.failed_dimensions == []
    assert len(report.blocking_findings) == 1


def test_a_major_finding_with_no_failures_sends_to_editorial_review() -> None:
    critique = _critique(findings=[_finding(severity=FindingSeverity.MAJOR)])

    service = ScriptQualityGateService()

    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    assert report.status == ScriptQualityStatus.EDITORIAL_REVIEW
    assert len(report.major_findings) == 1


def test_a_minor_finding_alone_still_approves() -> None:
    critique = _critique(findings=[_finding(severity=FindingSeverity.MINOR)])

    service = ScriptQualityGateService()

    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    assert report.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION


def test_a_dimension_the_critique_never_scored_is_not_gated() -> None:
    # Simulates a critique that, for whatever reason, never produced a
    # score for one of this genre's declared threshold dimensions -
    # the gate must skip it rather than treating a missing score as a
    # failure.
    critique = _critique(
        dimension_scores={
            "factual_confidence": 80,
            "retention_architecture": 80,
            # hook_strength intentionally absent.
        }
    )

    service = ScriptQualityGateService()

    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    assert "hook_strength" not in report.dimension_thresholds
    assert "hook_strength" not in report.failed_dimensions
    assert report.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION
