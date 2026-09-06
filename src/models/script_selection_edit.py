from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class SelectionEditOperation(str, Enum):
    """
    One selection-scoped AI edit action (Content Studio Redesign,
    Phase 12: "Selection actions: Rewrite/Shorten/Expand/More
    Suspenseful/More Natural/Improve Transition/Custom Instruction").
    """

    REWRITE = "rewrite"
    SHORTEN = "shorten"
    EXPAND = "expand"
    MORE_SUSPENSEFUL = "more_suspenseful"
    MORE_NATURAL = "more_natural"
    IMPROVE_TRANSITION = "improve_transition"
    CUSTOM = "custom"


class SelectionEditRequest(MissionBaseModel):
    """
    One request to edit part of a single script segment's narration.

    selected_text, when given, must be an exact substring of the
    target segment's narration - the edit applies to that slice while
    the rest of the segment's narration is supplied to the LLM as
    surrounding context (the "context envelope"); omitting it edits
    the segment's full narration instead. Every other segment, and the
    edited segment's timing/narrative_function/source claims, are
    always carried over unchanged by ScriptSelectionEditService - a
    selection edit only ever touches narration text.
    """

    segment_number: int = Field(ge=1)
    operation: SelectionEditOperation
    selected_text: str | None = None
    custom_instruction: str | None = None

    @field_validator("selected_text")
    @classmethod
    def clean_selected_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @field_validator("custom_instruction")
    @classmethod
    def clean_custom_instruction(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_custom_instruction(self) -> SelectionEditRequest:
        if (
            self.operation == SelectionEditOperation.CUSTOM
            and not self.custom_instruction
        ):
            raise ValueError("A CUSTOM selection edit requires a custom_instruction.")

        if self.operation != SelectionEditOperation.CUSTOM and self.custom_instruction:
            raise ValueError(
                "custom_instruction is only accepted for the CUSTOM operation."
            )

        return self
