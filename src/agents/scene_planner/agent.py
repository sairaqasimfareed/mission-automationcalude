from __future__ import annotations

import re

from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.story_blueprint import StoryBeatType
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.narration_timing_service import NarrationTimingService

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

# 2026-09-11 real fix, found live: plan() used to assign a flat 8
# seconds to every scene regardless of how long that scene's real
# narration actually takes to speak. A real, legitimate downstream
# safety check (VoiceDirectiveResolutionService, "narration duration
# exceeds scene duration") correctly refused to generate voice the
# moment a real sentence needed more than 8 seconds - a real scene
# from a real short-horror test script ("...a real, harmless
# condition called Exploding Head Syndrome.") needed roughly 12
# seconds. Kept as a floor, not replaced outright - a short sentence
# still gets at least this much screen time for reasonable pacing.
_MINIMUM_SCENE_DURATION_SECONDS = 8


class ScenePlannerAgent:
    """
    Splits an approved script into Veo-ready cinematic scenes.

    Two entry points, kept on one class rather than split into two
    services: plan() for the legacy, flat Script model (sentence
    splitting; each scene's duration is the real narration-timed
    estimate with an 8-second floor, not genre-aware density), and
    plan_from_generated_script() for the content intelligence engine's
    GeneratedScript (genre-aware density, tension-aware visual
    seeding). Both remain available so neither the old ContentPipeline
    nor the new ContentIntelligencePipeline breaks.

    Found via external audit: neither entry point ever set
    Scene.source_type explicitly, so every scene silently defaulted
    to the model's own MANUAL_UPLOAD default regardless of genre -
    Post-Script-Approval Production Plan Phase 6's "apply route
    defaults by project/genre" was never actually applied; only the
    per-clip override half (a person or a later stage changing one
    scene's own source_type) existed. genre_registry defaults to a
    real, populated instance rather than None - matching
    AudioCuePolicyService's own "no existing behavior for a
    default-off posture to protect" reasoning - since resolving a
    genre now only ever changes source_type/stock_query, fields every
    caller already left at their own prior defaults.
    """

    def __init__(
        self,
        *,
        genre_registry: GenreProfileRegistryService | None = None,
        narration_timing_service: NarrationTimingService | None = None,
    ) -> None:
        self._genre_registry = (
            genre_registry or GenreProfileRegistryService.with_default_profiles()
        )
        self._narration_timing_service = (
            narration_timing_service or NarrationTimingService()
        )

    def plan(self, script: Script, *, genre_id: str | None = None) -> list[Scene]:
        if script.status != ScriptStatus.APPROVED:
            raise ValueError("Scene planning requires an approved script.")

        # 2026-09-11 real fix, found live: this used to split on every
        # literal "." via script.content.split("."), which breaks on
        # anything but a bare sentence-ending period - a real script
        # containing "11:47 p.m." or markdown like "**Section:**"
        # produced real scene fragments as short as "O." or
        # ")**\n\nIt's 11:47 p.". Reuses the same lookbehind sentence
        # boundary regex _subdivide_segment() below already relies on
        # (requires trailing whitespace after ./!/?, so a mid-sentence
        # period isn't treated as a boundary) instead of a second,
        # cruder splitter.
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_PATTERN.split(script.content.strip())
            if sentence.strip()
        ]

        source_type = self._resolve_default_source_type(genre_id)

        scenes: list[Scene] = []

        for index, sentence in enumerate(sentences, start=1):
            # sentence already carries its own terminal punctuation
            # (the lookbehind split above keeps ./!/? attached to the
            # preceding text) - no longer appending a second "." here,
            # which used to build strings like "Really?." or
            # "...survive... Ultra realistic" before this fix.
            visual_prompt = (
                f"Cinematic visual inspired by: {sentence} "
                "Ultra realistic, cinematic lighting, "
                "volumetric atmosphere, high detail."
            )

            estimated_duration_seconds = max(
                _MINIMUM_SCENE_DURATION_SECONDS,
                self._narration_timing_service.estimate_seconds(len(sentence.split())),
            )

            scenes.append(
                Scene(
                    scene_number=index,
                    title=f"Scene {index}",
                    narration=sentence,
                    visual_prompt=visual_prompt,
                    estimated_duration_seconds=estimated_duration_seconds,
                    camera_direction="Slow cinematic push-in",
                    sound_design="Subtle cinematic ambience",
                    status=SceneStatus.READY,
                    source_type=source_type,
                    # Stock-footage scenes always require a
                    # stock_query - the same visual_prompt fallback
                    # scene_asset_workflow_service.py already uses
                    # when nothing more specific has been set yet.
                    stock_query=(
                        visual_prompt
                        if source_type == SceneSourceType.STOCK_FOOTAGE
                        else None
                    ),
                    metadata={
                        "source_script_id": str(script.id),
                    },
                )
            )

        return scenes

    def _resolve_default_source_type(
        self,
        genre_id: str | None,
    ) -> SceneSourceType:
        """
        Resolve this genre's default acquisition route.

        genre_id absent means "no genre was ever given" - preserves
        the exact prior MANUAL_UPLOAD-uniform behavior for every
        caller that doesn't (yet) pass one, rather than guessing a
        genre.
        """

        if genre_id is None:
            return SceneSourceType.MANUAL_UPLOAD

        resolution = self._genre_registry.resolve(genre_id, allow_fallback=True)

        if resolution.profile is None:
            return SceneSourceType.MANUAL_UPLOAD

        return resolution.profile.content_intelligence.default_scene_source_type

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
                        source_type=content_intelligence.default_scene_source_type,
                    )
                )
                scene_number += 1

        return scenes

    def _subdivide_segment(
        self,
        segment: ScriptSegment,
        *,
        scene_density_per_minute: float,
        average_visual_duration_seconds: float,
    ) -> list[tuple[list[str], float]]:
        """
        Return [(sentences, duration_seconds), ...] sub-scenes for one
        segment, in order, covering all of its narration exactly once.

        MRA-PRE-3 (Pre-Installer Master Audit) real finding: this used
        to split the segment's own time span EQUALLY across
        sub-scenes, with no regard for how much narration text ended
        up in each one - a chunk with more/longer sentences got the
        same duration as a chunk with fewer/shorter ones, and render's
        own voice-directive validation (a separate, correctly-working
        safety guard) would then refuse the whole run the moment any
        one chunk's actual narration took longer to speak than its
        allotted slice. Fixed: each chunk's duration is now the LARGER
        of (a) a proportional share of the segment's own time budget,
        weighted by that chunk's own estimated narration length - so a
        longer chunk still gets more time than a shorter one, exactly
        as genre density intends when the budget is sufficient - or
        (b) that chunk's own actual required narration duration (via
        NarrationTimingService, the same word-count-based estimate
        this codebase already uses elsewhere) - a hard floor, so a
        segment whose blueprint-assigned time span turns out to be
        genuinely too short for its own narration gets its total
        duration extended rather than having real speech silently
        squeezed into too little time. Only ever extends, never
        shrinks below what the genre's own density target already
        proposed - scene_density_per_minute/average_visual_duration_seconds
        still govern how many sub-scenes a segment splits into and,
        when the original time budget is sufficient, how that budget
        is shared between them.
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

        chunk_sentence_groups: list[list[str]] = []
        cursor = 0

        for index in range(sub_scene_count):
            chunk_size = base + (1 if index < extra else 0)
            chunk_sentence_groups.append(sentences[cursor : cursor + chunk_size])
            cursor += chunk_size

        # Matches ScriptSegment.word_count's own convention exactly
        # (len(text.split())) rather than inventing a second one.
        # NarrationTimingService.estimate_seconds() floors at 1, and
        # every chunk here always has at least one non-empty sentence
        # (sub_scene_count is capped at len(sentences) above), so
        # total_required_seconds is always >= sub_scene_count >= 1 -
        # no zero-division guard needed.
        required_seconds_by_chunk = [
            self._narration_timing_service.estimate_seconds(
                len(" ".join(chunk).split())
            )
            for chunk in chunk_sentence_groups
        ]
        total_required_seconds = sum(required_seconds_by_chunk)

        chunks: list[tuple[list[str], float]] = []

        for chunk, required_seconds in zip(
            chunk_sentence_groups, required_seconds_by_chunk, strict=True
        ):
            proportional_share = (
                required_seconds / total_required_seconds
            ) * duration_seconds
            chunks.append((chunk, max(proportional_share, required_seconds)))

        return chunks

    @staticmethod
    def _build_scene(
        *,
        scene_number: int,
        narration: str,
        duration_seconds: float,
        segment: ScriptSegment,
        topic: str,
        source_type: SceneSourceType,
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

        visual_prompt = (
            f"{beat_descriptor} for: {narration} "
            "Ultra realistic, cinematic lighting, volumetric "
            "atmosphere, high detail."
        )

        return Scene(
            scene_number=scene_number,
            title=f"Scene {scene_number} ({segment.narrative_function.value})",
            narration=narration,
            visual_prompt=visual_prompt,
            estimated_duration_seconds=max(1, round(duration_seconds)),
            camera_direction=camera_direction,
            sound_design="Subtle cinematic ambience",
            narrative_function=segment.narrative_function.value,
            status=SceneStatus.READY,
            source_type=source_type,
            # Stock-footage scenes always require a stock_query - the
            # same visual_prompt fallback scene_asset_workflow_service.py
            # already uses when nothing more specific has been set yet.
            stock_query=(
                visual_prompt if source_type == SceneSourceType.STOCK_FOOTAGE else None
            ),
            metadata={
                "source_segment_number": segment.segment_number,
                "tension_level": segment.tension_level,
                "topic": topic,
            },
        )
