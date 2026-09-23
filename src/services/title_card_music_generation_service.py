from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity
from src.models.music_generation import MusicGenerationResult
from src.models.resolved_editing_blueprint import (
    ResolvedMusicInstruction,
    ResolvedPresetReference,
)
from src.services.music_generation_service import MusicGenerationService


def _readable_genre_music_character(genre_music_preset_id: str) -> str:
    """Turn a preset id like "music.horror_low_drone" into "horror low
    drone" - a readable hint of the genre's own established musical
    character, reused as part of the title-card sting's own prompt
    rather than inventing a second, disconnected mood vocabulary."""

    _, _, suffix = genre_music_preset_id.partition(".")

    return (suffix or genre_music_preset_id).replace("_", " ").strip()


class TitleCardMusicGenerationService:
    """
    REQ-4 (opening title card): generate one dedicated, short musical
    sting for the title card - genuinely genre-flavored, built to grab
    attention in the first second rather than ease in like the main
    video's own ambient background track.

    Deliberately NOT a reused slice of the main video's own background
    music - see the design discussion this REQ was built from: reusing
    it either repeats the same seconds twice in a row once the main
    video starts, or couples the title card's own duration into the
    main timeline's audio positioning, exactly the kind of coupling
    REQ-4's fully-isolated, concat-prepended mechanism is meant to
    avoid. A genuinely separate, dedicated cue sidesteps both.

    Reuses MusicGenerationService (the same real, provider-independent
    generation path the main video's own background music already
    goes through) with a one-off "content_aware.custom" instruction,
    the same hand-construction pattern MusicPipelineStage's own
    _instruction_from_mood_segment() already uses for a one-off mood
    cue - not a second implementation of music-generation plumbing.
    """

    def __init__(
        self,
        *,
        music_generation_service: MusicGenerationService,
    ) -> None:
        self._music_generation_service = music_generation_service

    def generate(
        self,
        *,
        genre_music_preset_id: str,
        topic: str,
        duration_seconds: float,
        provider_name: str | None = None,
    ) -> MusicGenerationResult:
        genre_character = _readable_genre_music_character(genre_music_preset_id)

        library_query = (
            f"A short, catchy, attention-grabbing intro sting for a video "
            f"about {topic}. Musical character: {genre_character}. "
            "Must hook the listener from the very first second - no slow "
            "fade-in or ambient build-up."
        )

        preset = ResolvedPresetReference(
            directive_path="title_card.music",
            requested_preset_id="content_aware.custom",
            resolved_preset_id="content_aware.custom",
            found_exact_match=False,
            implementation={
                "library_query": library_query,
                "loop": False,
            },
        )

        instruction = ResolvedMusicInstruction(
            preset=preset,
            intensity=DirectiveIntensity.HIGH,
            volume_percent=100.0,
            fade_in_seconds=0.0,
            fade_out_seconds=0.3,
            duck_under_voice=False,
            enabled=True,
        )

        return self._music_generation_service.generate(
            instruction,
            duration_seconds=duration_seconds,
            provider_name=provider_name,
        )
