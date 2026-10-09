from __future__ import annotations

from pydantic import ValidationInfo, field_validator

from src.models.base import MissionBaseModel

_MAX_FIELD_LENGTH = 200
# The descriptive fields hold a sentence or two of concrete detail.
_MAX_SETTING_FIELD_LENGTH = 300

_STYLE_FIELDS = ("lighting", "color_palette", "camera_feel")
_SETTING_FIELDS = ("setting", "architecture", "climate", "sound")


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

    The project style sheet (2026-10-09) adds the world the video is set in: where and
    when (`setting`), what is built there (`architecture`), the weather and plants
    (`climate`) and what is heard (`sound`). Each is optional and only ever filled from
    what the script itself supports - a script that names no place or era leaves them
    empty, and empty adds nothing to any prompt.

    Deliberately not a per-scene setting: a scene that is genuinely at night keeps
    its own "Lighting:" line; this is the style the whole video is graded in.
    """

    lighting: str = ""
    color_palette: str = ""
    camera_feel: str = ""
    setting: str = ""
    architecture: str = ""
    climate: str = ""
    sound: str = ""

    @field_validator(*_STYLE_FIELDS, *_SETTING_FIELDS)
    @classmethod
    def clean_field(cls, value: str, info: ValidationInfo) -> str:
        cleaned = " ".join(value.split())
        limit = (
            _MAX_SETTING_FIELD_LENGTH
            if info.field_name in _SETTING_FIELDS
            else _MAX_FIELD_LENGTH
        )

        if len(cleaned) > limit:
            raise ValueError(f"A look field can be at most {limit} characters.")

        return cleaned.rstrip(".")

    @property
    def is_empty(self) -> bool:
        return not any(
            getattr(self, name) for name in (*_STYLE_FIELDS, *_SETTING_FIELDS)
        )

    def as_prompt_sentence(self) -> str:
        """The one sentence added to every prompt, or "" when nothing is set."""

        parts = [
            f"{label}: {value}"
            for label, value in (
                ("setting", self.setting),
                ("buildings and materials", self.architecture),
                ("climate and plants", self.climate),
                ("lighting", self.lighting),
                ("colour palette", self.color_palette),
                ("camera feel", self.camera_feel),
                ("background sound", self.sound),
            )
            if value
        ]

        if not parts:
            return ""

        return "Visual style for the whole video - " + "; ".join(parts) + "."
