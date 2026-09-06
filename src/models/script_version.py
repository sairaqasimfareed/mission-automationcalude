from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.generated_script import GeneratedScript


class ScriptChangeClass(str, Enum):
    """
    How consequential one script revision is, for downstream
    change-impact analysis (spec: does a revision invalidate
    already-generated scenes/voice/thumbnails, or is it safe to
    ignore downstream?).

    Ordered here from least to most consequential - STRUCTURAL and
    TIMING changes invalidate scene planning and voice timing;
    FACTUAL and NARRATIVE changes only invalidate narration-dependent
    assets (voice, subtitles) but flag that a fresh research or
    retention review may be worthwhile; STYLE_ONLY is the safe
    residual case.
    """

    STYLE_ONLY = "style_only"
    FACTUAL = "factual"
    NARRATIVE = "narrative"
    TIMING = "timing"
    STRUCTURAL = "structural"


class VersionReason(str, Enum):
    """
    Why one script version exists (Content Studio Redesign, Phase 12:
    "record reason per version"), independent of ScriptChangeClass
    (what changed structurally). A version is either the first draft,
    a person's own selection-based edit, an independent reviewer's
    critique-driven revision, a mechanical quality-gate-triggered fix,
    or a restore of an earlier version's content.
    """

    GENERATION = "generation"
    MANUAL_EDIT = "manual_edit"
    REVIEWER_REVISION = "reviewer_revision"
    QUALITY_FIX = "quality_fix"
    RESTORE = "restore"


class ScriptVersion(MissionBaseModel):
    """
    One immutable snapshot of a GeneratedScript in its revision
    lineage.

    Version 1 is the root (no parent, no change_class - there is
    nothing to classify a change against yet). Every later version
    must record which version it revised and why, so a project's
    script history is fully reconstructible.
    """

    version_number: int = Field(ge=1)
    script: GeneratedScript
    parent_version_number: int | None = Field(default=None, ge=1)
    change_class: ScriptChangeClass | None = None
    change_summary: str = Field(min_length=1)
    locked: bool = False
    # Optional so every existing caller (start_history's implicit v1,
    # add_revision's implicit critique-driven revision) keeps working
    # unchanged - the validator below fills in the same reason those
    # call sites already mean, and only Phase 12's new manual-edit and
    # restore paths need to pass an explicit value.
    reason: VersionReason | None = None
    # Only set when reason is RESTORE: which version's script content
    # this one copies. Distinct from parent_version_number (always the
    # version immediately before this one in the lineage, so the
    # sequential chain in ScriptVersionHistory stays intact even though
    # the *content* came from further back.
    restored_from_version_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_lineage(self) -> ScriptVersion:
        if self.version_number == 1:
            if self.parent_version_number is not None:
                raise ValueError("Version 1 cannot have a parent version.")

            if self.change_class is not None:
                raise ValueError(
                    "Version 1 has no change class - it is the root version."
                )

            if self.reason is None:
                self.reason = VersionReason.GENERATION
        else:
            if self.parent_version_number is None:
                raise ValueError(
                    "Every version after 1 requires a parent_version_number."
                )

            if self.parent_version_number >= self.version_number:
                raise ValueError("A version's parent must have a lower version_number.")

            if self.change_class is None:
                raise ValueError("Every version after 1 requires a change_class.")

            if self.reason is None:
                # Every pre-Phase-12 revision path was critique-driven.
                self.reason = VersionReason.REVIEWER_REVISION

        if (
            self.restored_from_version_number is not None
            and self.reason != VersionReason.RESTORE
        ):
            raise ValueError(
                "restored_from_version_number is only meaningful when reason "
                "is RESTORE."
            )

        if (
            self.reason == VersionReason.RESTORE
            and self.restored_from_version_number is None
        ):
            raise ValueError("A RESTORE version must set restored_from_version_number.")

        return self


class ScriptVersionHistory(MissionBaseModel):
    """The full revision lineage for one project's script."""

    topic: str = Field(min_length=1)
    versions: list[ScriptVersion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_versions(self) -> ScriptVersionHistory:
        ordered = sorted(self.versions, key=lambda version: version.version_number)
        expected_numbers = list(range(1, len(ordered) + 1))
        actual_numbers = [version.version_number for version in ordered]

        if actual_numbers != expected_numbers:
            raise ValueError(
                "Script version numbers must be sequential starting at 1: "
                f"got {actual_numbers}."
            )

        for version in ordered[1:]:
            if version.parent_version_number not in actual_numbers:
                raise ValueError(
                    f"Version {version.version_number} references an unknown "
                    f"parent version {version.parent_version_number}."
                )

        return self

    @property
    def current_version(self) -> ScriptVersion:
        """Return the most recent version in this history."""

        return max(self.versions, key=lambda version: version.version_number)

    @property
    def is_locked(self) -> bool:
        """Return whether the current version is locked against revision."""

        return self.current_version.locked

    def get_version(self, version_number: int) -> ScriptVersion:
        """Look up one version by number, or raise a clear error."""

        matched = next(
            (
                version
                for version in self.versions
                if version.version_number == version_number
            ),
            None,
        )

        if matched is None:
            raise ValueError(f"No version {version_number} exists in this history.")

        return matched


class ScriptSegmentDiff(MissionBaseModel):
    """
    One segment's before/after state between two script versions
    (Content Studio Redesign, Phase 12: version compare).

    segment_number identifies the segment by its position in the
    *later* version - an added segment has no "before" counterpart
    (narration_before is None), a removed one has no "after"
    counterpart (narration_after is None).
    """

    segment_number: int = Field(ge=1)
    narration_before: str | None = None
    narration_after: str | None = None
    timing_changed: bool = False
    narrative_function_changed: bool = False

    @property
    def status(self) -> str:
        if self.narration_before is None:
            return "added"

        if self.narration_after is None:
            return "removed"

        if (
            self.narration_before != self.narration_after
            or self.timing_changed
            or self.narrative_function_changed
        ):
            return "changed"

        return "unchanged"


class ScriptVersionComparison(MissionBaseModel):
    """The full segment-by-segment diff between two script versions."""

    from_version_number: int = Field(ge=1)
    to_version_number: int = Field(ge=1)
    segment_diffs: list[ScriptSegmentDiff] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(diff.status != "unchanged" for diff in self.segment_diffs)
