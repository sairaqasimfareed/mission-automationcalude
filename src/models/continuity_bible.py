from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ContinuityEntryType(str, Enum):
    """What kind of established fact one continuity entry records."""

    CHARACTER = "character"
    LOCATION = "location"
    TIMELINE = "timeline"
    FACT = "fact"


class ContinuityEntry(MissionBaseModel):
    """
    One fact established by the script that later segments must stay
    consistent with - a character's identity, a location, a point in
    the timeline, or any other stated fact worth tracking.
    """

    entry_type: ContinuityEntryType
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    first_mentioned_segment: int = Field(ge=1)

    @field_validator("name", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Continuity entry text cannot be empty.")

        return cleaned


class ContinuityBible(MissionBaseModel):
    """
    Every character, location, timeline point, and standalone fact a
    script establishes, extracted once so later revisions or a human
    editor can check new narration against what was already stated -
    the same purpose a TV writers' room "bible" serves.
    """

    topic: str = Field(min_length=1)
    entries: list[ContinuityEntry] = Field(default_factory=list)
    prompt_version: str = Field(min_length=1)

    @property
    def characters(self) -> list[ContinuityEntry]:
        return [
            e for e in self.entries if e.entry_type == ContinuityEntryType.CHARACTER
        ]

    @property
    def locations(self) -> list[ContinuityEntry]:
        return [e for e in self.entries if e.entry_type == ContinuityEntryType.LOCATION]

    @property
    def timeline_facts(self) -> list[ContinuityEntry]:
        return [e for e in self.entries if e.entry_type == ContinuityEntryType.TIMELINE]

    @property
    def facts(self) -> list[ContinuityEntry]:
        return [e for e in self.entries if e.entry_type == ContinuityEntryType.FACT]


class ContinuityInconsistency(MissionBaseModel):
    """
    Two mentions of the same named entry whose descriptions differ -
    a mechanical "these disagree, review them" flag, not a claim that
    either mention is actually wrong (that judgment needs a human or
    an LLM reading both in context, neither of which this model does).
    """

    entry_type: ContinuityEntryType
    name: str = Field(min_length=1)
    first_description: str = Field(min_length=1)
    first_segment: int = Field(ge=1)
    later_description: str = Field(min_length=1)
    later_segment: int = Field(ge=1)


class ContinuityValidationResult(MissionBaseModel):
    """Result of checking one ContinuityBible for same-name conflicts."""

    topic: str = Field(min_length=1)
    inconsistencies: list[ContinuityInconsistency] = Field(default_factory=list)

    @property
    def is_consistent(self) -> bool:
        """Return whether no conflicting mentions were found."""

        return not self.inconsistencies
