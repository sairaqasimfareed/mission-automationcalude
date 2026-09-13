from __future__ import annotations

from src.models.continuity_bible import ContinuityBible
from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)
from src.models.scene import Scene
from src.models.sound_design_plan import (
    MusicMoodSegment,
    SoundDesignPlan,
    SoundEffectCueDirective,
)
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_VALID_INTENSITIES = {intensity.value for intensity in DirectiveIntensity}
_VALID_TIMING_MODES = {mode.value for mode in DirectiveTimingMode}

_DRY_RUN_RESPONSE = "\n---\n".join(
    (
        "TYPE: SFX\n"
        "SCENE: 1\n"
        "PROMPT: dry-run sound effect cue for development and testing "
        "purposes only\n"
        "PRESET_ID: NONE\n"
        "TIMING: scene_middle\n"
        "VOLUME: 70\n"
        "INTENSITY: medium\n"
        "RATIONALE: Dry-run rationale.",
        "TYPE: MUSIC\n"
        "START_SCENE: 1\n"
        "END_SCENE: 1\n"
        "MOOD: dry-run mood description for development and testing "
        "purposes only\n"
        "INTENSITY: medium\n"
        "RATIONALE: Dry-run rationale.",
    )
)


class SceneSoundDesignService:
    """
    Generate a content-aware SoundDesignPlan: scene-specific SFX cues
    written from each scene's actual narration, plus a music mood
    curve across the video - replacing a fixed genre-wide preset list
    applied identically to every scene regardless of content.

    One batched LLM call for the whole video, not one per scene,
    matching the cost discipline every other content-intelligence
    service in this codebase already follows.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated sound design generation cost cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        scenes: list[Scene],
        genre_tone: str,
        genre_narrative_architecture_hint: str,
        available_preset_ids: list[str] | None = None,
        continuity_bible: ContinuityBible | None = None,
    ) -> SoundDesignPlan:
        """
        Generate one SoundDesignPlan covering every supplied scene.

        available_preset_ids lets the model reuse an existing,
        already-QA'd EffectRegistryService preset when one genuinely
        fits, instead of always writing a bespoke generation prompt -
        cheaper and more consistent when a close match exists.
        """

        if not scenes:
            raise ValueError("Sound design generation requires at least one scene.")

        ordered_scenes = sorted(scenes, key=lambda scene: scene.scene_number)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                scenes=ordered_scenes,
                genre_tone=genre_tone,
                genre_narrative_architecture_hint=(genre_narrative_architecture_hint),
                available_preset_ids=(available_preset_ids or []),
                continuity_bible=continuity_bible,
            ),
            system_prompt=(
                "You are a professional sound designer and music "
                "supervisor for short-form video. Propose sound "
                "effects and background-music direction grounded in "
                "the actual narration of each scene - never invent a "
                "generic ambience cue that could apply to any scene. "
                "Only propose a sound effect when the narration "
                "genuinely calls for one; many scenes should have "
                "zero sound-effect cues."
            ),
            prompt_version="scene_sound_design_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "SceneSoundDesignService",
                "workflow": "sound_design",
                "scene_count": len(ordered_scenes),
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(f"Sound design generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Sound design provider returned empty content.")

        valid_scene_numbers = {scene.scene_number for scene in ordered_scenes}

        sfx_cues, music_segments, warnings = self._parse_plan(
            content,
            valid_scene_numbers=valid_scene_numbers,
        )

        return SoundDesignPlan(
            sfx_cues=sfx_cues,
            music_segments=music_segments,
            provider=service_result.result.provider,
            model=service_result.result.model,
            warnings=warnings,
        )

    @staticmethod
    def _build_prompt(
        *,
        scenes: list[Scene],
        genre_tone: str,
        genre_narrative_architecture_hint: str,
        available_preset_ids: list[str],
        continuity_bible: ContinuityBible | None,
    ) -> str:
        scene_lines = "\n".join(
            f"SCENE {scene.scene_number} "
            f"({scene.estimated_duration_seconds}s): {scene.narration}"
            for scene in scenes
        )

        continuity_section = ""

        if continuity_bible is not None and continuity_bible.entries:
            continuity_lines = "\n".join(
                f"- {entry.entry_type.value}: {entry.name} - {entry.description}"
                for entry in continuity_bible.entries
            )
            continuity_section = (
                "\nEstablished continuity facts (keep recurring "
                f"locations/characters sonically consistent):\n{continuity_lines}\n"
            )

        preset_section = ""

        if available_preset_ids:
            preset_list = ", ".join(available_preset_ids)
            preset_section = (
                "\nExisting sound-effect presets you may reuse when one "
                f"genuinely fits (set PRESET_ID to its id instead of "
                f"writing a new PROMPT): {preset_list}\n"
            )

        return (
            f"Genre tone: {genre_tone}\n"
            f"Narrative architecture: {genre_narrative_architecture_hint}\n"
            f"{continuity_section}"
            f"{preset_section}\n"
            f"Scenes:\n{scene_lines}\n\n"
            "For each scene, decide whether it genuinely calls for a "
            "sound effect - most scenes should have zero or one, only "
            "add a second when the narration clearly describes two "
            "distinct sound events. Then propose a background-music "
            "mood curve across scene ranges (it does not need to "
            "change every scene - group consecutive scenes that share "
            "the same mood into one segment).\n\n"
            "Return each sound-effect cue as its own block and each "
            "music segment as its own block, separated by a line of "
            "three or more dashes.\n\n"
            "Sound-effect cue block:\n"
            "TYPE: SFX\n"
            "SCENE: <scene number>\n"
            "PROMPT: <a concrete, descriptive sound-generation prompt "
            "grounded in this scene's narration>\n"
            "PRESET_ID: <an id from the reusable list above, or NONE>\n"
            "TIMING: <one of: scene_start, scene_middle, scene_end, "
            "relative_percent>\n"
            "POSITION_PERCENT: <0-100, only if TIMING is "
            "relative_percent, else omit>\n"
            "VOLUME: <0-100>\n"
            "INTENSITY: <one of: very_low, low, medium, high, "
            "very_high>\n"
            "RATIONALE: <the specific narration phrase that "
            "motivated this cue>\n\n"
            "Music mood segment block:\n"
            "TYPE: MUSIC\n"
            "START_SCENE: <scene number>\n"
            "END_SCENE: <scene number, same as START_SCENE if only "
            "one scene>\n"
            "MOOD: <a concrete music-generation mood/style prompt>\n"
            "INTENSITY: <one of: very_low, low, medium, high, "
            "very_high>\n"
            "RATIONALE: <why this range shares this mood>"
        )

    @classmethod
    def _parse_plan(
        cls,
        content: str,
        *,
        valid_scene_numbers: set[int],
    ) -> tuple[list[SoundEffectCueDirective], list[MusicMoodSegment], list[str]]:
        sfx_cues: list[SoundEffectCueDirective] = []
        music_segments: list[MusicMoodSegment] = []
        warnings: list[str] = []

        for block in split_blocks(content):
            block_type = (extract_labeled_field(block, "TYPE") or "").strip().upper()

            if block_type == "SFX":
                cue = cls._parse_sfx_cue(
                    block,
                    valid_scene_numbers=valid_scene_numbers,
                    warnings=warnings,
                )

                if cue is not None:
                    sfx_cues.append(cue)

            elif block_type == "MUSIC":
                segment = cls._parse_music_segment(
                    block,
                    valid_scene_numbers=valid_scene_numbers,
                    warnings=warnings,
                )

                if segment is not None:
                    music_segments.append(segment)

        return sfx_cues, music_segments, warnings

    @classmethod
    def _parse_sfx_cue(
        cls,
        block: str,
        *,
        valid_scene_numbers: set[int],
        warnings: list[str],
    ) -> SoundEffectCueDirective | None:
        scene_raw = extract_labeled_field(block, "SCENE")
        prompt = extract_labeled_field(block, "PROMPT")
        rationale = extract_labeled_field(block, "RATIONALE")

        if not scene_raw or not scene_raw.strip().isdigit():
            warnings.append("Skipped an SFX cue with a missing/invalid SCENE.")

            return None

        scene_number = int(scene_raw.strip())

        if scene_number not in valid_scene_numbers:
            warnings.append(
                f"Skipped an SFX cue referencing unknown scene {scene_number}."
            )

            return None

        if not prompt or not rationale:
            warnings.append(
                f"Skipped an SFX cue for scene {scene_number} missing "
                "PROMPT or RATIONALE."
            )

            return None

        preset_id = extract_labeled_field(block, "PRESET_ID")
        normalized_preset_id = (
            preset_id.strip()
            if preset_id and preset_id.strip().upper() != "NONE"
            else None
        )

        timing_raw = (extract_labeled_field(block, "TIMING") or "").strip().lower()
        timing_mode = (
            DirectiveTimingMode(timing_raw)
            if timing_raw in _VALID_TIMING_MODES
            else DirectiveTimingMode.ABSOLUTE_SECONDS
        )

        position_percent = cls._parse_optional_float(
            extract_labeled_field(block, "POSITION_PERCENT")
        )

        volume = cls._parse_optional_float(extract_labeled_field(block, "VOLUME"))

        intensity_raw = (
            (extract_labeled_field(block, "INTENSITY") or "").strip().lower()
        )
        intensity = (
            DirectiveIntensity(intensity_raw)
            if intensity_raw in _VALID_INTENSITIES
            else DirectiveIntensity.MEDIUM
        )

        return SoundEffectCueDirective(
            scene_number=scene_number,
            generation_prompt=prompt,
            preset_id=normalized_preset_id,
            timing_mode=timing_mode,
            relative_position_percent=(
                position_percent
                if timing_mode == DirectiveTimingMode.RELATIVE_PERCENT
                else None
            ),
            volume_percent=(volume if volume is not None else 70.0),
            intensity=intensity,
            rationale=rationale,
        )

    @classmethod
    def _parse_music_segment(
        cls,
        block: str,
        *,
        valid_scene_numbers: set[int],
        warnings: list[str],
    ) -> MusicMoodSegment | None:
        start_raw = extract_labeled_field(block, "START_SCENE")
        end_raw = extract_labeled_field(block, "END_SCENE")
        mood = extract_labeled_field(block, "MOOD")
        rationale = extract_labeled_field(block, "RATIONALE")

        if not start_raw or not start_raw.strip().isdigit():
            warnings.append(
                "Skipped a music segment with a missing/invalid START_SCENE."
            )

            return None

        if not end_raw or not end_raw.strip().isdigit():
            warnings.append("Skipped a music segment with a missing/invalid END_SCENE.")

            return None

        start_scene = int(start_raw.strip())
        end_scene = int(end_raw.strip())

        if (
            start_scene not in valid_scene_numbers
            or end_scene not in valid_scene_numbers
        ):
            warnings.append(
                "Skipped a music segment referencing unknown scenes "
                f"{start_scene}-{end_scene}."
            )

            return None

        if not mood or not rationale:
            warnings.append(
                f"Skipped a music segment ({start_scene}-{end_scene}) missing "
                "MOOD or RATIONALE."
            )

            return None

        if end_scene < start_scene:
            warnings.append(
                f"Skipped a music segment with END_SCENE {end_scene} before "
                f"START_SCENE {start_scene}."
            )

            return None

        intensity_raw = (
            (extract_labeled_field(block, "INTENSITY") or "").strip().lower()
        )
        intensity = (
            DirectiveIntensity(intensity_raw)
            if intensity_raw in _VALID_INTENSITIES
            else DirectiveIntensity.MEDIUM
        )

        return MusicMoodSegment(
            start_scene_number=start_scene,
            end_scene_number=end_scene,
            mood_description=mood,
            intensity=intensity,
            rationale=rationale,
        )

    @staticmethod
    def _parse_optional_float(raw: str | None) -> float | None:
        if raw is None:
            return None

        try:
            return float(raw.strip())
        except ValueError:
            return None
