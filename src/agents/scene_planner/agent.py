from __future__ import annotations

import re

from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.story_blueprint import StoryBeatType

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")

# Short cinematic descriptor per structural beat (spec: scene
# semantic intent should inform visual direction, not just genre
# presets applied uniformly). Deliberately a phrase, not a closed
# production instruction - GenreDirectiveGenerationService's presets
# remain the actual source of camera/effect presets; this only seeds
# the scene's own visual_prompt/camera_direction text.
_BEAT_VISUAL_DESCRIPTORS: dict[StoryBeatType, str] = {
    StoryBeatType.HOOK: "A striking, attention-grabbing opening image",
    StoryBeatType.SETUP: "A grounded, establishing visual",
    StoryBeatType.REVEAL: "A visual that exposes new information",
    StoryBeatType.RE_HOOK: "A visual callback that renews the open question",
    StoryBeatType.ESCALATION: "An intensifying, higher-energy visual",
    StoryBeatType.MAJOR_REVELATION: "A dramatic, high-impact reveal visual",
    StoryBeatType.CLIMAX: "A peak-intensity, high-stakes visual",
    StoryBeatType.PAYOFF: "A resolving visual that delivers on the setup",
    StoryBeatType.AFTERSHOCK: "A quieter, reflective visual",
}

# Camera language derived from a segment's own tension_level (spec
# section 27's tension curve, already numeric per segment) rather
# than the coarser beat type alone - two HOOK segments can carry
# different tension.
_HIGH_TENSION_THRESHOLD = 70
_MODERATE_TENSION_THRESHOLD = 40


class ScenePlannerAgent:
    """
    Splits an approved script into Veo-ready cinematic scenes.

    Two entry points, kept on one class rather than split into two
    services: plan() for the legacy, flat Script model (sentence
    splitting, hardcoded duration, no genre awareness - unchanged),
    and plan_from_generated_script() for the content intelligence
    engine's GeneratedScript (genre-aware density, tension-aware
    visual seeding). Both remain available so neither the old
    ContentPipeline nor the new ContentIntelligencePipeline breaks.
    """

    def plan(self, script: Script) -> list[Scene]:
        if script.status != ScriptStatus.APPROVED:
            raise ValueError("Scene planning requires an approved script.")

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

    def plan_from_generated_script(
        self,
        script: GeneratedScript,
        editorial_profile: EditorialProfile,
    ) -> list[Scene]:
        """
        Plan genre-aware scenes from a content-intelligence
        GeneratedScript.

        Each segment's boundaries already carry a real structural
        decision (StoryBeatType, timing, tension) from the story
        blueprint - this subdivides each one into visual-length
        sub-scenes using the genre's scene_density_per_minute as the
        target count and average_visual_duration_seconds as a floor
        against over-fragmenting a short segment, rather than
        splitting on sentence punctuation with a fixed 8s guess.
        """

        content_intelligence = editorial_profile.content_intelligence
        ordered_segments = sorted(
            script.segments, key=lambda segment: segment.start_seconds
        )

        scenes: list[Scene] = []
        scene_number = 1

        for segment in ordered_segments:
            for sentences, sub_duration_seconds in self._subdivide_segment(
                segment,
                scene_density_per_minute=content_intelligence.scene_density_per_minute,
                average_visual_duration_seconds=(
                    content_intelligence.average_visual_duration_seconds
                ),
            ):
                narration = " ".join(sentences)

                scenes.append(
                    self._build_scene(
                        scene_number=scene_number,
                        narration=narration,
                        duration_seconds=sub_duration_seconds,
                        segment=segment,
                        topic=script.topic,
                    )
                )
                scene_number += 1

        return scenes

    @classmethod
    def _subdivide_segment(
        cls,
        segment: ScriptSegment,
        *,
        scene_density_per_minute: float,
        average_visual_duration_seconds: float,
    ) -> list[tuple[list[str], float]]:
        """
        Return [(sentences, duration_seconds), ...] sub-scenes for one
        segment, in order, covering all of its narration exactly once.
        """

        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_PATTERN.split(segment.narration.strip())
            if sentence.strip()
        ] or [segment.narration.strip()]

        duration_seconds = segment.end_seconds - segment.start_seconds

        target_count = max(1, round(scene_density_per_minute * duration_seconds / 60))

        if average_visual_duration_seconds > 0:
            max_count_by_floor = max(
                1, int(duration_seconds // average_visual_duration_seconds)
            )
            target_count = min(target_count, max_count_by_floor)

        sub_scene_count = max(1, min(target_count, len(sentences)))

        base, extra = divmod(len(sentences), sub_scene_count)
        sub_scene_duration = duration_seconds / sub_scene_count

        chunks: list[tuple[list[str], float]] = []
        cursor = 0

        for index in range(sub_scene_count):
            chunk_size = base + (1 if index < extra else 0)
            chunk = sentences[cursor : cursor + chunk_size]
            cursor += chunk_size
            chunks.append((chunk, sub_scene_duration))

        return chunks

    @staticmethod
    def _build_scene(
        *,
        scene_number: int,
        narration: str,
        duration_seconds: float,
        segment: ScriptSegment,
        topic: str,
    ) -> Scene:
        beat_descriptor = _BEAT_VISUAL_DESCRIPTORS.get(
            segment.narrative_function, "A cinematic visual"
        )

        if segment.tension_level >= _HIGH_TENSION_THRESHOLD:
            camera_direction = "Quick push-in, urgent handheld energy"
        elif segment.tension_level >= _MODERATE_TENSION_THRESHOLD:
            camera_direction = "Steady push-in, moderate movement"
        else:
            camera_direction = "Slow, mostly static hold"

        return Scene(
            scene_number=scene_number,
            title=f"Scene {scene_number} ({segment.narrative_function.value})",
            narration=narration,
            visual_prompt=(
                f"{beat_descriptor} for: {narration} "
                "Ultra realistic, cinematic lighting, volumetric "
                "atmosphere, high detail."
            ),
            estimated_duration_seconds=max(1, round(duration_seconds)),
            camera_direction=camera_direction,
            sound_design="Subtle cinematic ambience",
            narrative_function=segment.narrative_function.value,
            status=SceneStatus.READY,
            metadata={
                "source_segment_number": segment.segment_number,
                "tension_level": segment.tension_level,
                "topic": topic,
            },
        )
