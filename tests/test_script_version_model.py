from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_version import (
    ScriptChangeClass,
    ScriptSegmentDiff,
    ScriptVersion,
    ScriptVersionComparison,
    ScriptVersionHistory,
    VersionReason,
)
from src.models.story_blueprint import StoryBeatType


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
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _root_version() -> ScriptVersion:
    return ScriptVersion(
        version_number=1,
        script=_script(),
        change_summary="Initial generated script.",
    )


def test_root_version_constructs() -> None:
    version = _root_version()

    assert version.version_number == 1
    assert version.parent_version_number is None
    assert version.change_class is None


def test_root_version_rejects_a_parent_version_number() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=1,
            script=_script(),
            parent_version_number=1,
            change_summary="Initial generated script.",
        )


def test_root_version_rejects_a_change_class() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=1,
            script=_script(),
            change_class=ScriptChangeClass.STYLE_ONLY,
            change_summary="Initial generated script.",
        )


def test_later_version_requires_a_parent_version_number() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=2,
            script=_script(),
            change_class=ScriptChangeClass.STYLE_ONLY,
            change_summary="A revision.",
        )


def test_later_version_requires_a_change_class() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=2,
            script=_script(),
            parent_version_number=1,
            change_summary="A revision.",
        )


def test_later_version_parent_must_be_a_lower_number() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=2,
            script=_script(),
            parent_version_number=2,
            change_class=ScriptChangeClass.STYLE_ONLY,
            change_summary="A revision.",
        )


def _revision(*, version_number: int, parent: int) -> ScriptVersion:
    return ScriptVersion(
        version_number=version_number,
        script=_script(f"Revised narration v{version_number}."),
        parent_version_number=parent,
        change_class=ScriptChangeClass.STYLE_ONLY,
        change_summary="A revision.",
    )


def test_history_requires_sequential_version_numbers() -> None:
    with pytest.raises(ValidationError):
        ScriptVersionHistory(
            topic="The Mary Celeste",
            versions=[_root_version(), _revision(version_number=3, parent=1)],
        )


def test_history_rejects_an_unknown_parent_reference() -> None:
    with pytest.raises(ValidationError):
        ScriptVersionHistory(
            topic="The Mary Celeste",
            versions=[_root_version(), _revision(version_number=2, parent=5)],
        )


def test_current_version_returns_the_highest_version_number() -> None:
    history = ScriptVersionHistory(
        topic="The Mary Celeste",
        versions=[
            _root_version(),
            _revision(version_number=2, parent=1),
            _revision(version_number=3, parent=2),
        ],
    )

    assert history.current_version.version_number == 3


def test_is_locked_reflects_the_current_version() -> None:
    locked_v2 = _revision(version_number=2, parent=1).model_copy(
        update={"locked": True}
    )
    history = ScriptVersionHistory(
        topic="The Mary Celeste",
        versions=[_root_version(), locked_v2],
    )

    assert history.is_locked is True


def test_root_version_defaults_reason_to_generation() -> None:
    assert _root_version().reason == VersionReason.GENERATION


def test_later_version_without_an_explicit_reason_defaults_to_reviewer_revision() -> (
    None
):
    assert (
        _revision(version_number=2, parent=1).reason == VersionReason.REVIEWER_REVISION
    )


def test_version_accepts_an_explicit_reason() -> None:
    version = ScriptVersion(
        version_number=2,
        script=_script(),
        parent_version_number=1,
        change_class=ScriptChangeClass.STYLE_ONLY,
        change_summary="A manual edit.",
        reason=VersionReason.MANUAL_EDIT,
    )

    assert version.reason == VersionReason.MANUAL_EDIT


def test_restore_reason_requires_restored_from_version_number() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=2,
            script=_script(),
            parent_version_number=1,
            change_class=ScriptChangeClass.STYLE_ONLY,
            change_summary="Restored.",
            reason=VersionReason.RESTORE,
        )


def test_restored_from_version_number_requires_restore_reason() -> None:
    with pytest.raises(ValidationError):
        ScriptVersion(
            version_number=2,
            script=_script(),
            parent_version_number=1,
            change_class=ScriptChangeClass.STYLE_ONLY,
            change_summary="Not actually a restore.",
            reason=VersionReason.MANUAL_EDIT,
            restored_from_version_number=1,
        )


def test_restore_reason_with_source_constructs() -> None:
    version = ScriptVersion(
        version_number=2,
        script=_script(),
        parent_version_number=1,
        change_class=ScriptChangeClass.STYLE_ONLY,
        change_summary="Restored from version 1.",
        reason=VersionReason.RESTORE,
        restored_from_version_number=1,
    )

    assert version.restored_from_version_number == 1


def test_get_version_returns_the_matching_version() -> None:
    history = ScriptVersionHistory(
        topic="The Mary Celeste",
        versions=[_root_version(), _revision(version_number=2, parent=1)],
    )

    assert history.get_version(2).version_number == 2


def test_get_version_raises_for_an_unknown_version_number() -> None:
    history = ScriptVersionHistory(topic="The Mary Celeste", versions=[_root_version()])

    with pytest.raises(ValueError, match="No version 7"):
        history.get_version(7)


def test_segment_diff_status_added() -> None:
    diff = ScriptSegmentDiff(segment_number=1, narration_after="New text.")

    assert diff.status == "added"


def test_segment_diff_status_removed() -> None:
    diff = ScriptSegmentDiff(segment_number=1, narration_before="Old text.")

    assert diff.status == "removed"


def test_segment_diff_status_unchanged() -> None:
    diff = ScriptSegmentDiff(
        segment_number=1, narration_before="Same.", narration_after="Same."
    )

    assert diff.status == "unchanged"


def test_version_comparison_has_changes_reflects_any_non_unchanged_diff() -> None:
    comparison = ScriptVersionComparison(
        from_version_number=1,
        to_version_number=2,
        segment_diffs=[
            ScriptSegmentDiff(
                segment_number=1, narration_before="Same.", narration_after="Same."
            )
        ],
    )

    assert comparison.has_changes is False
