from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class DirectiveSource(str, Enum):
    """
    Where one writing directive came from (Content Studio Redesign,
    Phase 11: Script Workspace - Writing Directives).

    Precedence for conflicts is judged by the Reviewer (see
    ReviewerService's ArtifactType.DIRECTIVES focus guidance), not
    hardcoded here as a priority order - the redesign's own wording
    only requires storing source and overridability per directive, not
    a mechanical precedence resolution algorithm.
    """

    SYSTEM = "system"
    GENRE = "genre"
    PROJECT = "project"
    USER = "user"


class WritingDirective(MissionBaseModel):
    """
    One explicit writing rule to follow during script generation.

    `overridable` is stored per-directive rather than derived purely
    from `source` - the redesign asks for both fields independently -
    but every SYSTEM-source directive WritingDirectivesService produces
    is always overridable=False, mechanically enforcing "System
    factual-grounding rules cannot be disabled by ordinary user
    directives": no code path in this codebase constructs a SYSTEM
    directive any other way.
    """

    text: str = Field(min_length=1)
    source: DirectiveSource
    overridable: bool

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Writing directive text cannot be empty.")

        return cleaned


class WritingDirectiveSet(MissionBaseModel):
    """
    The resolved, coherent set of writing directives for one project's
    script generation - kept as its own artifact, distinct from Story
    Architecture, per this phase's own goal.
    """

    directives: list[WritingDirective] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    @property
    def system_directives(self) -> list[WritingDirective]:
        """The always-present, non-overridable directives in this set."""

        return [d for d in self.directives if d.source == DirectiveSource.SYSTEM]
