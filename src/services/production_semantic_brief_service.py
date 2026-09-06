from __future__ import annotations

from uuid import UUID

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.genre_profile import GenreProfile
from src.models.production_semantic_brief import (
    ProductionSemanticBrief,
    ProductionSemanticSegment,
)
from src.models.story_blueprint import StoryBlueprint


class ProductionSemanticBriefService:
    """
    Post-Script-Approval Production Plan, Phase 1: "Translate the
    locked narrative into time-bounded production intent before any
    media is generated."

    Deliberately pure/deterministic, no LLM call - every input this
    needs already exists on the locked script and its genre profile
    (segment timing/narrative_function/tension_level/curiosity-loop
    tagging/claim references come straight from GeneratedScript's own
    already-validated, gapless segments; visual/voice/music/SFX/
    editing/transition intent are deterministic genre-preset lookups,
    the same kind GenreDirectiveGenerationService already makes for
    Scene-level directives). A brief built this way is exactly
    reproducible from unchanged inputs, which is what "artifact
    hash/version for downstream staleness detection" requires.
    """

    def generate(
        self,
        *,
        script: GeneratedScript,
        genre_profile: GenreProfile,
        script_lock_hash: str,
        story_blueprint: StoryBlueprint | None = None,
    ) -> ProductionSemanticBrief:
        segments = [
            self._build_segment(
                segment,
                genre_profile=genre_profile,
                story_blueprint=story_blueprint,
            )
            for segment in script.segments
        ]

        return ProductionSemanticBrief(
            script_lock_hash=script_lock_hash,
            target_duration_seconds=script.target_duration_seconds,
            segments=segments,
        )

    @staticmethod
    def _build_segment(
        segment: ScriptSegment,
        *,
        genre_profile: GenreProfile,
        story_blueprint: StoryBlueprint | None,
    ) -> ProductionSemanticSegment:
        beat_id: UUID | None = None

        if story_blueprint is not None:
            # Bind by real-seconds time range - the same matching
            # trick Content Studio Redesign Phase 9's
            # _bind_curiosity_roles() already established for tying a
            # script segment back to the beat that produced it,
            # rather than re-deriving a second binding mechanism.
            for beat in story_blueprint.beats:
                if beat.start_seconds <= segment.start_seconds < beat.end_seconds:
                    beat_id = beat.id
                    break

        script_profile = genre_profile.script
        voice_profile = genre_profile.voice
        editing_profile = genre_profile.editing

        return ProductionSemanticSegment(
            segment_number=segment.segment_number,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            beat_id=beat_id,
            beat_type=segment.narrative_function.value,
            narrative_intent=(
                f"{segment.narrative_function.value.replace('_', ' ').title()} "
                f"beat - {script_profile.narrative_style} narrative style."
            ),
            emotional_intent=(
                f"Tension level {segment.tension_level}/100, "
                f"{script_profile.tone.value} tone."
            ),
            pacing_intent=f"{script_profile.pacing.value} pacing.",
            visual_intent=(
                f"Camera preset '{editing_profile.camera_preset_id}'; "
                f"visual presets: "
                f"{', '.join(editing_profile.visual_preset_ids) or 'genre default'}."
            ),
            voice_intent=(
                f"Emotion '{voice_profile.emotion}', pace "
                f"'{voice_profile.pace.value}', energy "
                f"'{voice_profile.energy.value}'."
            ),
            music_intent=f"Music preset '{editing_profile.music_preset_id}'.",
            sfx_intent=(
                "Genre-default sound effects (no dedicated per-segment SFX "
                "cue resolved yet - see Phase 10 Music/SFX Acquisition)."
            ),
            editing_intent=(
                f"Animation presets: "
                f"{', '.join(editing_profile.animation_preset_ids) or 'genre default'}."
            ),
            transition_intent=(
                f"In: '{editing_profile.transition_in_preset_id}', "
                f"out: '{editing_profile.transition_out_preset_id}'."
            ),
            reveal_protected=segment.related_curiosity_loop is not None,
            related_curiosity_loop=segment.related_curiosity_loop,
            supporting_claims=list(segment.source_claim_references),
        )
