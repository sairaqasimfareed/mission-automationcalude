"""The story treatment: how the video OPENS and what recurs, proposed for the operator to accept.

Live, 2026-10-10 (Haunted wife): the video opened on a close-up of a letter, and nothing in it ever
recurred to build dread - so a horror story played as a documentary. A treatment is two proposals made
from the script, both for the operator to accept or discard (nothing is applied on its own):

- the opening image (`hook_visual`), the first thing a viewer sees; and
- a recurring presence (a person or place the script already names, glimpsed in a few scenes), which is
  an ordinary `IdentitySuggestion` and goes through the same Accept flow as every other suggested
  character - this model only remembers its name.

Neither adds an event, person or object the narration does not contain; they are treatment of what the
script already says.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.suggestions import SuggestionStatus


class StoryTreatment(MissionBaseModel):
    hook_visual: str = Field(min_length=1, max_length=600)
    hook_status: SuggestionStatus = SuggestionStatus.PENDING
    # The recurring presence proposed alongside it (its description lives in the project's
    # identity suggestions, and in the continuity bible once accepted). "" when none.
    motif_name: str = Field(default="", max_length=60)

    @field_validator("hook_visual", "motif_name")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def accepted_hook(self) -> str:
        """The opening image to build scene 1 around, or "" unless it was accepted."""

        return self.hook_visual if self.hook_status == SuggestionStatus.ACCEPTED else ""
