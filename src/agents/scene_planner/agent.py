from __future__ import annotations

from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus


class ScenePlannerAgent:
    """Splits an approved script into Veo-ready cinematic scenes."""

    def plan(self, script: Script) -> list[Scene]:
        if script.status != ScriptStatus.APPROVED:
            raise ValueError(
                "Scene planning requires an approved script."
            )

        sentences = [
            sentence.strip()
            for sentence in script.content.split(".")
            if sentence.strip()
        ]

        scenes: list[Scene] = []

        for index, sentence in enumerate(sentences, start=1):
            scenes.append(
                Scene(
                    scene_number=index,
                    title=f"Scene {index}",
                    narration=f"{sentence}.",
                    visual_prompt=(
                        f"Cinematic visual inspired by: {sentence}. "
                        "Ultra realistic, cinematic lighting, "
                        "volumetric atmosphere, high detail."
                    ),
                    estimated_duration_seconds=8,
                    camera_direction="Slow cinematic push-in",
                    sound_design="Subtle cinematic ambience",
                    status=SceneStatus.READY,
                    metadata={
                        "source_script_id": str(script.id),
                    },
                )
            )

        return scenes