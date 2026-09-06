from __future__ import annotations

from src.models.production_ambiguity import ProductionAmbiguity
from src.models.script_production_readiness import ScriptProductionReadinessReport


def _blocking_ambiguity() -> ProductionAmbiguity:
    return ProductionAmbiguity(
        description="Unclear character identity.",
        continuity_critical=True,
    )


def test_is_ready_true_when_everything_present_and_no_blocking_ambiguities() -> None:
    report = ScriptProductionReadinessReport(
        has_continuity_bible=True, has_scenes=True, scene_count=3
    )

    assert report.is_ready is True


def test_is_ready_false_without_a_continuity_bible() -> None:
    report = ScriptProductionReadinessReport(
        has_continuity_bible=False, has_scenes=True, scene_count=3
    )

    assert report.is_ready is False


def test_is_ready_false_without_scenes() -> None:
    report = ScriptProductionReadinessReport(
        has_continuity_bible=True, has_scenes=False, scene_count=0
    )

    assert report.is_ready is False


def test_is_ready_false_with_a_blocking_ambiguity() -> None:
    report = ScriptProductionReadinessReport(
        has_continuity_bible=True,
        has_scenes=True,
        scene_count=3,
        unresolved_blocking_ambiguities=[_blocking_ambiguity()],
    )

    assert report.is_ready is False
