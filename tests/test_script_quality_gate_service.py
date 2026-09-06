from __future__ import annotations

import pytest

from src.models.editorial_critique import (
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
)
from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_quality_report import ScriptQualityStatus
from src.models.story_blueprint import StoryBeatType
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


def _script(narration: str = "The crew vanished without a trace.") -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=30,
                narrative_function=StoryBeatType.HOOK,
                narration=narration,
                tension_level=60,
            )
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def test_evaluate_without_a_script_leaves_the_binding_fields_unset() -> None:
    service = ScriptQualityGateService()

    report = service.evaluate(
        critique=_critique(), editorial_profile=_mystery_profile()
    )

    assert report.script_version_number is None
    assert report.script_content_hash is None


def test_evaluate_with_a_script_binds_version_and_hash() -> None:
    service = ScriptQualityGateService()

    report = service.evaluate(
        critique=_critique(),
        editorial_profile=_mystery_profile(),
        script=_script(),
        script_version_number=2,
    )

    assert report.script_version_number == 2
    assert report.script_content_hash is not None
    assert len(report.script_content_hash) == 64  # sha256 hex digest


def test_evaluate_hash_is_deterministic_for_identical_scripts() -> None:
    service = ScriptQualityGateService()

    first = service.evaluate(
        critique=_critique(), editorial_profile=_mystery_profile(), script=_script()
    )
    second = service.evaluate(
        critique=_critique(), editorial_profile=_mystery_profile(), script=_script()
    )

    assert first.script_content_hash == second.script_content_hash


def test_evaluate_hash_differs_when_narration_changes() -> None:
    service = ScriptQualityGateService()

    first = service.evaluate(
        critique=_critique(), editorial_profile=_mystery_profile(), script=_script()
    )
    second = service.evaluate(
        critique=_critique(),
        editorial_profile=_mystery_profile(),
        script=_script("A completely different opening line."),
    )

    assert first.script_content_hash != second.script_content_hash


def test_ignore_finding_records_a_resolution() -> None:
    finding = _finding(severity=FindingSeverity.BLOCKING)
    critique = _critique(findings=[finding])
    service = ScriptQualityGateService()
    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    updated = service.ignore_finding(
        report=report, finding_id=finding.id, reason="Acceptable for this genre."
    )

    resolution = updated.resolution_for(finding.id)
    assert resolution is not None
    assert resolution.reason == "Acceptable for this genre."
    assert updated.unresolved_blocking_findings == []


def test_ignore_finding_rejects_an_unknown_finding_id() -> None:
    critique = _critique(findings=[_finding(severity=FindingSeverity.BLOCKING)])
    service = ScriptQualityGateService()
    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    with pytest.raises(ValueError, match="No finding"):
        service.ignore_finding(
            report=report, finding_id=_finding().id, reason="Doesn't matter."
        )


def test_ignore_finding_rejects_an_empty_reason() -> None:
    finding = _finding(severity=FindingSeverity.BLOCKING)
    critique = _critique(findings=[finding])
    service = ScriptQualityGateService()
    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())

    with pytest.raises(ValueError, match="non-empty reason"):
        service.ignore_finding(report=report, finding_id=finding.id, reason="   ")


def test_ignore_finding_rejects_a_finding_already_resolved() -> None:
    finding = _finding(severity=FindingSeverity.BLOCKING)
    critique = _critique(findings=[finding])
    service = ScriptQualityGateService()
    report = service.evaluate(critique=critique, editorial_profile=_mystery_profile())
    once = service.ignore_finding(
        report=report, finding_id=finding.id, reason="First reason."
    )

    with pytest.raises(ValueError, match="already has a resolution"):
        service.ignore_finding(
            report=once, finding_id=finding.id, reason="Second reason."
        )
