from __future__ import annotations

import pytest

from src.models.editorial_critique import (
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
)
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_version import ScriptChangeClass, VersionReason
from src.models.story_blueprint import StoryBeatType
from src.services.script_version_service import ScriptVersionService


def _segment(
    *,
    number: int = 1,
    start: float = 0,
    end: float = 30,
    narrative_function: StoryBeatType = StoryBeatType.HOOK,
    narration: str = "The crew vanished without a trace.",
) -> ScriptSegment:
    return ScriptSegment(
        segment_number=number,
        start_seconds=start,
        end_seconds=end,
        narrative_function=narrative_function,
        narration=narration,
        tension_level=60,
    )


def _script(*segments: ScriptSegment) -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=list(segments) or [_segment()],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _finding(dimension: str, **overrides: object) -> CriticFinding:
    base: dict[str, object] = dict(
        dimension=dimension,
        severity=FindingSeverity.MAJOR,
        segment_number=1,
        problem="Something is wrong.",
        reason="It matters.",
        recommended_correction="Fix it.",
    )
    base.update(overrides)
    return CriticFinding(**base)


def _critique(*findings: CriticFinding) -> EditorialCritique:
    return EditorialCritique(
        topic="The Mary Celeste",
        dimension_scores={"narrative_coherence": 50},
        findings=list(findings),
        prompt_version="editorial_critique_prompt_v1.0.0",
    )


def test_start_history_creates_the_root_version() -> None:
    service = ScriptVersionService()
    script = _script()

    history = service.start_history(topic="The Mary Celeste", script=script)

    assert len(history.versions) == 1
    assert history.current_version.version_number == 1
    assert history.current_version.change_class is None


def test_start_history_rejects_empty_topic() -> None:
    service = ScriptVersionService()

    with pytest.raises(ValueError, match="cannot be empty"):
        service.start_history(topic="   ", script=_script())


def test_add_revision_classifies_a_structural_change() -> None:
    service = ScriptVersionService()
    original = _script(_segment(number=1), _segment(number=2, start=30, end=60))
    history = service.start_history(topic="The Mary Celeste", script=original)

    # Segment count dropped from 2 to 1 - a structural change.
    revised = _script(_segment(number=1))

    updated = service.add_revision(
        history=history, revised_script=revised, critique=_critique()
    )

    assert updated.current_version.change_class == ScriptChangeClass.STRUCTURAL


def test_add_revision_classifies_a_timing_change() -> None:
    service = ScriptVersionService()
    original = _script(_segment(start=0, end=30))
    history = service.start_history(topic="The Mary Celeste", script=original)

    revised = _script(_segment(start=0, end=25))

    updated = service.add_revision(
        history=history, revised_script=revised, critique=_critique()
    )

    assert updated.current_version.change_class == ScriptChangeClass.TIMING


def test_add_revision_classifies_a_factual_change_from_critique_findings() -> None:
    service = ScriptVersionService()
    original = _script(_segment(narration="The captain died at sea."))
    history = service.start_history(topic="The Mary Celeste", script=original)

    revised = _script(_segment(narration="The captain's fate remains unknown."))
    critique = _critique(_finding("factual_confidence"))

    updated = service.add_revision(
        history=history, revised_script=revised, critique=critique
    )

    assert updated.current_version.change_class == ScriptChangeClass.FACTUAL


def test_add_revision_classifies_a_narrative_change_from_critique_findings() -> None:
    service = ScriptVersionService()
    original = _script(_segment(narration="Old narration."))
    history = service.start_history(topic="The Mary Celeste", script=original)

    revised = _script(_segment(narration="New narration with more tension."))
    critique = _critique(_finding("retention_architecture"))

    updated = service.add_revision(
        history=history, revised_script=revised, critique=critique
    )

    assert updated.current_version.change_class == ScriptChangeClass.NARRATIVE


def test_add_revision_defaults_to_style_only_with_no_matching_findings() -> None:
    service = ScriptVersionService()
    original = _script(_segment(narration="Old narration."))
    history = service.start_history(topic="The Mary Celeste", script=original)

    revised = _script(_segment(narration="Slightly reworded narration."))
    critique = _critique(_finding("hook_strength"))

    updated = service.add_revision(
        history=history, revised_script=revised, critique=critique
    )

    assert updated.current_version.change_class == ScriptChangeClass.STYLE_ONLY


def test_add_revision_appends_with_correct_lineage() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    updated = service.add_revision(
        history=history,
        revised_script=_script(_segment(narration="Revised.")),
        critique=_critique(),
    )

    assert len(updated.versions) == 2
    assert updated.current_version.version_number == 2
    assert updated.current_version.parent_version_number == 1


def test_add_revision_raises_when_current_version_is_locked() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())
    locked = service.lock_version(history=history, version_number=1)

    with pytest.raises(ValueError, match="is locked"):
        service.add_revision(
            history=locked,
            revised_script=_script(_segment(narration="Revised.")),
            critique=_critique(),
        )


def test_unlock_version_allows_revision_to_resume() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())
    locked = service.lock_version(history=history, version_number=1)
    unlocked = service.unlock_version(history=locked, version_number=1)

    updated = service.add_revision(
        history=unlocked,
        revised_script=_script(_segment(narration="Revised.")),
        critique=_critique(),
    )

    assert len(updated.versions) == 2


def test_lock_version_raises_for_an_unknown_version_number() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    with pytest.raises(ValueError, match="No version 5"):
        service.lock_version(history=history, version_number=5)


def test_add_manual_edit_records_a_manual_edit_reason() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    updated = service.add_manual_edit(
        history=history,
        revised_script=_script(_segment(narration="Person-edited narration.")),
        change_summary="Segment 1: rewrite.",
    )

    assert updated.current_version.version_number == 2
    assert updated.current_version.reason == VersionReason.MANUAL_EDIT
    assert updated.current_version.change_class == ScriptChangeClass.STYLE_ONLY


def test_add_manual_edit_still_classifies_structural_changes_mechanically() -> None:
    service = ScriptVersionService()
    original = _script(_segment(number=1), _segment(number=2, start=30, end=60))
    history = service.start_history(topic="The Mary Celeste", script=original)

    revised = _script(_segment(number=1))

    updated = service.add_manual_edit(
        history=history, revised_script=revised, change_summary="Removed a segment."
    )

    assert updated.current_version.change_class == ScriptChangeClass.STRUCTURAL


def test_add_manual_edit_rejects_an_empty_change_summary() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    with pytest.raises(ValueError, match="non-empty change summary"):
        service.add_manual_edit(
            history=history, revised_script=_script(), change_summary="   "
        )


def test_add_manual_edit_raises_when_current_version_is_locked() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())
    locked = service.lock_version(history=history, version_number=1)

    with pytest.raises(ValueError, match="is locked"):
        service.add_manual_edit(
            history=locked, revised_script=_script(), change_summary="Edit."
        )


def test_add_manual_edit_accepts_a_quality_fix_reason_override() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    updated = service.add_manual_edit(
        history=history,
        revised_script=_script(_segment(narration="Fixed narration.")),
        change_summary="Fixed a quality-gate finding.",
        reason=VersionReason.QUALITY_FIX,
    )

    assert updated.current_version.reason == VersionReason.QUALITY_FIX


def test_restore_version_copies_an_earlier_versions_script() -> None:
    service = ScriptVersionService()
    v1_script = _script(_segment(narration="Original narration."))
    history = service.start_history(topic="The Mary Celeste", script=v1_script)

    history = service.add_manual_edit(
        history=history,
        revised_script=_script(_segment(narration="Edited narration.")),
        change_summary="An edit.",
    )

    restored = service.restore_version(history=history, version_number=1)

    assert restored.current_version.version_number == 3
    assert restored.current_version.reason == VersionReason.RESTORE
    assert restored.current_version.restored_from_version_number == 1
    assert restored.current_version.script.full_narration == v1_script.full_narration
    # Restoring never removes what it restored from - v1 and v2 both
    # still exist in the lineage.
    assert len(restored.versions) == 3


def test_restore_version_raises_for_an_unknown_version_number() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    with pytest.raises(ValueError, match="No version 9"):
        service.restore_version(history=history, version_number=9)


def test_restore_version_raises_when_current_version_is_locked() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())
    locked = service.lock_version(history=history, version_number=1)

    with pytest.raises(ValueError, match="is locked"):
        service.restore_version(history=locked, version_number=1)


def test_compare_reports_no_changes_for_a_version_against_itself() -> None:
    service = ScriptVersionService()
    history = service.start_history(topic="The Mary Celeste", script=_script())

    comparison = service.compare(
        history=history, from_version_number=1, to_version_number=1
    )

    assert comparison.has_changes is False


def test_compare_reports_a_changed_segment() -> None:
    service = ScriptVersionService()
    history = service.start_history(
        topic="The Mary Celeste",
        script=_script(_segment(narration="Original narration.")),
    )
    history = service.add_manual_edit(
        history=history,
        revised_script=_script(_segment(narration="Edited narration.")),
        change_summary="An edit.",
    )

    comparison = service.compare(
        history=history, from_version_number=1, to_version_number=2
    )

    assert comparison.has_changes is True
    diff = comparison.segment_diffs[0]
    assert diff.narration_before == "Original narration."
    assert diff.narration_after == "Edited narration."
    assert diff.status == "changed"


def test_compare_reports_added_and_removed_segments() -> None:
    service = ScriptVersionService()
    history = service.start_history(
        topic="The Mary Celeste",
        script=_script(_segment(number=1), _segment(number=2, start=30, end=60)),
    )
    history = service.add_manual_edit(
        history=history,
        revised_script=_script(
            _segment(number=1), _segment(number=3, start=60, end=90)
        ),
        change_summary="Swapped a segment.",
    )

    comparison = service.compare(
        history=history, from_version_number=1, to_version_number=2
    )

    by_number = {diff.segment_number: diff for diff in comparison.segment_diffs}
    assert by_number[2].status == "removed"
    assert by_number[3].status == "added"
