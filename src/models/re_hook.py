from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ReHookType(str, Enum):
    """What kind of new information a re-hook introduces (spec section 31)."""

    NEW_QUESTION = "new_question"
    CONTRADICTION = "contradiction"
    UNEXPECTED_DETAIL = "unexpected_detail"
    INCREASED_STAKES = "increased_stakes"
    PARTIAL_REVELATION = "partial_revelation"
    PERSPECTIVE_CHANGE = "perspective_change"
    NEW_THREAT = "new_threat"


class ReHook(MissionBaseModel):
    """One re-hook: a moment that re-establishes viewer curiosity."""

    position_seconds: float = Field(ge=0.0)
    re_hook_type: ReHookType
    text: str = Field(min_length=1, max_length=300)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Re-hook text cannot be empty.")

        return cleaned


class ReHookPlan(MissionBaseModel):
    """
    Every re-hook planned for one video (spec section 31).

    Re-hook count and timing come from the story blueprint's own
    re_hook beats (spec section 26) - this model only carries their
    content, so timing is decided once, not twice.
    """

    topic: str = Field(min_length=1)
    re_hooks: list[ReHook] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    @property
    def repetitive_phrasing(self) -> list[str]:
        """
        Re-hook texts that exactly duplicate another re-hook's text
        in this plan (spec section 31: "detect repetitive template
        language") - e.g. reusing "But that's not the scary part."
        for every re-hook. Limited to exact-normalized duplicates,
        the same honest scope limitation as
        CuriosityLoopValidationService's redundant_loops check.
        """

        seen: set[str] = set()
        duplicates: list[str] = []
        reported: set[str] = set()

        for re_hook in self.re_hooks:
            key = re_hook.text.strip().lower()

            if key in seen and key not in reported:
                duplicates.append(re_hook.text)
                reported.add(key)

            seen.add(key)

        return duplicates
