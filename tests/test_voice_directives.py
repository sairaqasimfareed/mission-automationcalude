from __future__ import annotations

from src.models.voice_directives import (
    PronunciationDirective,
    SceneVoiceDirectives,
    VoiceDirectiveSource,
    VoiceDirectiveStatus,
    VoiceEmotion,
    VoiceEmphasisDirective,
    VoiceEmphasisStyle,
    VoiceEnergy,
    VoicePace,
    VoicePauseDirective,
    VoicePauseStyle,
    VoicePitchStyle,
    VoiceProviderPreferences,
)


directives = SceneVoiceDirectives(
    scene_number=1,
    voice_profile_id="voice.horror_whisper",
    fallback_voice_profile_id=(
        "voice.neutral_narrator"
    ),
    language="English",
    language_code="en-US",
    emotion=VoiceEmotion.SUSPENSEFUL,
    pace=VoicePace.SLOW,
    energy=VoiceEnergy.LOW,
    pitch_style=VoicePitchStyle.DEEP,
    pause_style=VoicePauseStyle.DRAMATIC,
    emphasis_style=(
        VoiceEmphasisStyle.SELECTIVE
    ),
    speed=0.9,
    pitch_adjustment=-2.0,
    volume_gain_db=1.0,
    stability=0.7,
    similarity_boost=0.8,
    style_strength=0.45,
    speaker_boost=True,
    pause_before_seconds=0.3,
    pause_after_seconds=0.5,
    pronunciation_directives=[
        PronunciationDirective(
            text="Derinkuyu",
            pronunciation=(
                "de-rin-ku-yu"
            ),
            alphabet="phonetic",
        ),
    ],
    pause_directives=[
        VoicePauseDirective(
            after_text=(
                "The door slowly opened."
            ),
            duration_seconds=1.2,
        ),
    ],
    emphasis_directives=[
        VoiceEmphasisDirective(
            text="never",
            strength=0.8,
        ),
    ],
    provider_preferences=(
        VoiceProviderPreferences(
            preferred_provider=(
                "ElevenLabs"
            ),
            preferred_model=(
                "eleven_multilingual_v2"
            ),
            preferred_voice_id=(
                "horror-narrator-001"
            ),
            preferred_output_format="mp3",
            fallback_providers=[
                "OpenAI",
                "Google TTS",
                "OpenAI",
            ],
        )
    ),
    source=(
        VoiceDirectiveSource.GENRE_PROFILE
    ),
    status=VoiceDirectiveStatus.DRAFT,
    metadata={
        "genre_id": "genre.horror",
    },
)

print(
    "Voice profile:",
    directives.voice_profile_id,
)

print(
    "Emotion:",
    directives.emotion,
)

print(
    "Explicit instructions:",
    directives.explicit_instruction_count,
)

assert directives.scene_number == 1

assert (
    directives.voice_profile_id
    == "voice.horror_whisper"
)

assert (
    directives.fallback_voice_profile_id
    == "voice.neutral_narrator"
)

assert (
    directives.emotion
    == VoiceEmotion.SUSPENSEFUL
)

assert directives.speed == 0.9

assert (
    directives.explicit_instruction_count
    == 3
)

assert (
    directives.provider_preferences
    .preferred_provider
    == "ElevenLabs"
)

assert (
    directives.provider_preferences
    .fallback_providers
    == [
        "OpenAI",
        "Google TTS",
    ]
)


default_directives = (
    SceneVoiceDirectives(
        scene_number=2,
    )
)

assert (
    default_directives.voice_profile_id
    == "voice.neutral_narrator"
)

assert (
    default_directives.emotion
    == VoiceEmotion.NEUTRAL
)

assert (
    default_directives.pace
    == VoicePace.MODERATE
)

# Same fallback as primary is removed safely.
assert (
    default_directives
    .fallback_voice_profile_id
    is None
)


try:
    SceneVoiceDirectives(
        scene_number=3,
        voice_profile_id=(
            "horror_whisper"
        ),
    )
except ValueError:
    print(
        "Invalid voice profile ID "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Voice profile without prefix "
        "should fail."
    )


try:
    SceneVoiceDirectives(
        scene_number=4,
        speed=2.5,
    )
except ValueError:
    print(
        "Invalid voice speed "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Voice speed above limit "
        "should fail."
    )


try:
    VoicePauseDirective(
        duration_seconds=1.0,
    )
except ValueError:
    print(
        "Pause without location "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Pause requires a location."
    )


try:
    SceneVoiceDirectives(
        scene_number=5,
        pronunciation_directives=[
            PronunciationDirective(
                text="Derinkuyu",
                pronunciation="first",
            ),
            PronunciationDirective(
                text="derinkuyu",
                pronunciation="second",
            ),
        ],
    )
except ValueError:
    print(
        "Duplicate pronunciation "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Duplicate pronunciation "
        "directives should fail."
    )


try:
    VoiceProviderPreferences(
        preferred_output_format="exe",
    )
except ValueError:
    print(
        "Invalid voice format "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Unsupported audio format "
        "should fail."
    )


serialized = directives.model_dump_json()

restored = (
    SceneVoiceDirectives
    .model_validate_json(
        serialized
    )
)

assert restored == directives

assert restored.schema_version == "1.0"


print(
    "Voice Directive model tests "
    "completed successfully."
)