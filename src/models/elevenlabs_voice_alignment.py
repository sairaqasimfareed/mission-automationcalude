from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class ElevenLabsVoiceCharacterAlignment(MissionBaseModel):
    """
    Real ElevenLabs character-level timing data - the exact shape
    returned by the real text-to-speech-with-timestamps endpoint
    (POST /v1/text-to-speech/{voice_id}/with-timestamps), verified
    directly against ElevenLabs' own current API documentation
    (2026-09-09), not assumed.

    Voice gap #8's real fix: enables accurate caption/subtitle sync
    instead of an estimate, since each character's real start/end time
    (in seconds, relative to this generation's own audio) is known.
    """

    characters: list[str] = Field(default_factory=list)

    character_start_times_seconds: list[float] = Field(default_factory=list)

    character_end_times_seconds: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_equal_lengths(self) -> ElevenLabsVoiceCharacterAlignment:
        lengths = {
            len(self.characters),
            len(self.character_start_times_seconds),
            len(self.character_end_times_seconds),
        }

        if len(lengths) > 1:
            raise ValueError(
                "ElevenLabs character alignment arrays must all be the " "same length."
            )

        return self

    @property
    def character_count(self) -> int:
        return len(self.characters)


class ElevenLabsVoiceWithTimestampsResult(MissionBaseModel):
    """
    Result of a real ElevenLabs text-to-speech-with-timestamps call -
    the audio file (already written to disk, and pitch-shifted if
    requested, exactly like generate_from_blueprint()'s own output)
    plus the real character alignment data ElevenLabs returned
    alongside it.

    alignment/normalized_alignment are both optional because
    ElevenLabs' own documented response marks both as nullable -
    never fabricated when absent.
    """

    output_file: str

    alignment: ElevenLabsVoiceCharacterAlignment | None = None

    normalized_alignment: ElevenLabsVoiceCharacterAlignment | None = None
