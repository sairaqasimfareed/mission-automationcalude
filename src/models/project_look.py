from __future__ import annotations

from pydantic import field_validator

from src.models.base import MissionBaseModel

_MAX_FIELD_LENGTH = 200


class ProjectLook(MissionBaseModel):
    """
    The video-wide visual style, written once and repeated word for word in every
    scene's prompt.

    Live, 2026-10-06 (Lake Nyos): scene 1 came out overcast and muted and scene 2
    sunny and saturated, because each prompt carried only its own vague lighting
    phrase ("Soft, natural daylight" / "Natural daylight") and nothing anchored the
    look across scenes. These fields are the anchor. They are separate on purpose -
    lighting, colour and camera feel are the three things that drift independently -
    and any may be left empty.

    Deliberately not a per-scene setting: a scene that is genuinely at night keeps
    its own "Lighting:" line; this is the style the whole video is graded in.
    """

    lighting: str = ""
    color_palette: str = ""
    camera_feel: str = ""

    @field_validator("lighting", "color_palette", "camera_feel")
    @classmethod
    def clean_field(cls, value: str) -> str:
        cleaned = " ".join(value.split())

        if len(cleaned) > _MAX_FIELD_LENGTH:
            raise ValueError(
                f"A look field can be at most {_MAX_FIELD_LENGTH} characters."
            )

        return cleaned.rstrip(".")

    @property
    def is_empty(self) -> bool:
        return not (self.lighting or self.color_palette or self.camera_feel)

    def as_prompt_sentence(self) -> str:
        """The one sentence added to every prompt, or "" when nothing is set."""

        parts = [
            f"{label}: {value}"
            for label, value in (
                ("lighting", self.lighting),
                ("colour palette", self.color_palette),
                ("camera feel", self.camera_feel),
            )
            if value
        ]

        if not parts:
            return ""

        return "Visual style for the whole video - " + "; ".join(parts) + "."
