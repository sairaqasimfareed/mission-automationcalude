from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

MAX_SCENE_DETAIL_CHARACTERS = 1200


class SceneDetail(MissionBaseModel):
    """
    The scene-specific part of one clip's prompt, written in concrete visual words
    (2026-10-09): where things stand in the frame, the direction and quality of the
    light, textures and objects, how the camera moves through the shot, the mood and
    the sound of the place.

    The compiler assembles everything that repeats from the project (style sheet, place
    and character descriptions) and the shot plan; this is the one part only a writer
    can supply per scene. `source_hash` records what it was written from (see
    `scene_detail_source_hash`): when the narration, shot or setting changes, the text
    is stale and the compiler stops using it rather than send a description of a scene
    that no longer exists.
    """

    scene_number: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=MAX_SCENE_DETAIL_CHARACTERS)
    source_hash: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split()).rstrip(".")


class SceneDetailPlan(MissionBaseModel):
    """Every scene's detail text, kept on the VideoJob so it survives a restart."""

    details: list[SceneDetail] = Field(default_factory=list)

    def detail_for(self, scene_number: int) -> SceneDetail | None:
        for detail in self.details:
            if detail.scene_number == scene_number:
                return detail

        return None

    def current_text_for(self, scene_number: int, source_hash: str) -> str:
        """The scene's detail text, or "" when there is none or it was written from
        something that has since changed."""

        detail = self.detail_for(scene_number)

        if detail is None or detail.source_hash != source_hash:
            return ""

        return detail.text
