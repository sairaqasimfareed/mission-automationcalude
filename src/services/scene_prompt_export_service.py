from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from src.models.cinematic_prompt import CinematicPromptPackage
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

    Post-Script-Approval Production Plan, Phase 4/5: prefers a
    project's resolved ResolvedCinematicPrompt.prompt_text (compiled
    from structured shot/continuity/semantic data) over the legacy
    Scene.visual_prompt whenever a cinematic_prompt_package is
    supplied and has an entry for that scene - "current desktop
    shortcut must be replaced" / "every generation request uses a
    persisted validated prompt," found via inspection while wiring
    Phase 5's Clip Workspace integration, not assumed. Falls back to
    scene.visual_prompt for any scene the package doesn't cover (an
    older project, or one where the new chain hasn't been run yet),
    so nothing regresses for a project that never touches Phase 0-4.
    """

    def build_entries(
        self,
        scenes: list[Scene],
        *,
        cinematic_prompt_package: CinematicPromptPackage | None = None,
    ) -> list[ScenePromptExportEntry]:
        ordered = sorted(scenes, key=lambda scene: scene.scene_number)

        return [
            ScenePromptExportEntry(
                scene_number=scene.scene_number,
                suggested_filename=self._suggested_filename(scene),
                prompt=self._resolve_prompt_text(scene, cinematic_prompt_package),
                camera_direction=scene.camera_direction,
                estimated_duration_seconds=scene.estimated_duration_seconds,
            )
            for scene in ordered
        ]

    def to_text(
        self,
        scenes: list[Scene],
        *,
        cinematic_prompt_package: CinematicPromptPackage | None = None,
    ) -> str:
        blocks = [
            (
                f"Scene {entry.scene_number} -> save the downloaded clip as: "
                f"{entry.suggested_filename}\n"
                f"Prompt: {entry.prompt}\n"
                f"Camera: {entry.camera_direction or 'unspecified'}\n"
                f"Target duration: {entry.estimated_duration_seconds}s"
            )
            for entry in self.build_entries(
                scenes, cinematic_prompt_package=cinematic_prompt_package
            )
        ]

        if not blocks:
            return "No scenes to export."

        return "\n\n---\n\n".join(blocks)

    def write_file(
        self,
        scenes: list[Scene],
        destination: Path,
        *,
        cinematic_prompt_package: CinematicPromptPackage | None = None,
    ) -> None:
        destination.write_text(
            self.to_text(scenes, cinematic_prompt_package=cinematic_prompt_package),
            encoding="utf-8",
        )

    @staticmethod
    def _resolve_prompt_text(
        scene: Scene, cinematic_prompt_package: CinematicPromptPackage | None
    ) -> str:
        if cinematic_prompt_package is not None:
            resolved = cinematic_prompt_package.prompt_for_scene(scene.scene_number)

            if resolved is not None:
                return resolved.prompt_text

        return scene.visual_prompt

    @staticmethod
    def _suggested_filename(scene: Scene) -> str:
        return f"{scene.scene_number:03d}_{_slugify(scene.title)}.mp4"
