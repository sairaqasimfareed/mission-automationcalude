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

    @model_validator(mode="after")
    def validate_lineage(self) -> ScriptVersion:
        if self.version_number == 1:
            if self.parent_version_number is not None:
                raise ValueError("Version 1 cannot have a parent version.")

            if self.change_class is not None:
                raise ValueError(
                    "Version 1 has no change class - it is the root version."
                )
        else:
            if self.parent_version_number is None:
                raise ValueError(
                    "Every version after 1 requires a parent_version_number."
                )

            if self.parent_version_number >= self.version_number:
                raise ValueError("A version's parent must have a lower version_number.")

            if self.change_class is None:
                raise ValueError("Every version after 1 requires a change_class.")

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
