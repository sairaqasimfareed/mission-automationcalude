from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from src.models.scene import Scene

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 60


def _slugify(text: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", text.strip().lower()).strip("-")

    return normalized[:_MAX_SLUG_LENGTH] or "scene"


class ScenePromptExportEntry(NamedTuple):
    """One scene's exported generation prompt, ready to hand to an
    external AI video tool by hand."""

    scene_number: int
    suggested_filename: str
    prompt: str
    camera_direction: str
    estimated_duration_seconds: int


class ScenePromptExportService:
    """
    Exports every scene's already-generated cinematic prompt into a
    single reviewable list, with a suggested filename per scene that
    BulkClipIngestionService's filename-matching later relies on.

    Deliberately just a formatting/export step - it does not call any
    external AI generation tool. A human takes this list to whatever
    tool they use (Google Flow or otherwise) by hand.
    """

    def build_entries(self, scenes: list[Scene]) -> list[ScenePromptExportEntry]:
        ordered = sorted(scenes, key=lambda scene: scene.scene_number)

        return [
            ScenePromptExportEntry(
                scene_number=scene.scene_number,
                suggested_filename=self._suggested_filename(scene),
                prompt=scene.visual_prompt,
                camera_direction=scene.camera_direction,
                estimated_duration_seconds=scene.estimated_duration_seconds,
            )
            for scene in ordered
        ]

    def to_text(self, scenes: list[Scene]) -> str:
        blocks = [
            (
                f"Scene {entry.scene_number} -> save the downloaded clip as: "
                f"{entry.suggested_filename}\n"
                f"Prompt: {entry.prompt}\n"
                f"Camera: {entry.camera_direction or 'unspecified'}\n"
                f"Target duration: {entry.estimated_duration_seconds}s"
            )
            for entry in self.build_entries(scenes)
        ]

        if not blocks:
            return "No scenes to export."

        return "\n\n---\n\n".join(blocks)

    def write_file(self, scenes: list[Scene], destination: Path) -> None:
        destination.write_text(self.to_text(scenes), encoding="utf-8")

    @staticmethod
    def _suggested_filename(scene: Scene) -> str:
        return f"{scene.scene_number:03d}_{_slugify(scene.title)}.mp4"
