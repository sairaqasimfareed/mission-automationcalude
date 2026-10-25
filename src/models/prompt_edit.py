from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

MAX_PROMPT_EDIT_CHARACTERS = 12_000


class PromptEdit(MissionBaseModel):
    """A prompt the operator wrote by hand for one scene (or one part of a split scene).

    The automatic prompt is never touched: this is kept beside it and sent instead of it.
    `automatic_hash` fingerprints the automatic prompt the edit was made against, so the Prompts
    tab can say "the automatic prompt has changed since you edited this" instead of silently
    keeping or replacing either text.
    """

    scene_number: int = Field(ge=1)
    clip_sequence_index: int = Field(default=0, ge=0)
    text: str = Field(min_length=1, max_length=MAX_PROMPT_EDIT_CHARACTERS)
    automatic_hash: str = ""

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        # Line breaks the operator typed are kept; only the ends are trimmed.
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("A prompt edit cannot be empty.")

        return cleaned
