from __future__ import annotations

from src.models.resolved_voice_blueprint import (
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_directives import (
    PronunciationDirective,
    SceneVoiceDirectives,
    VoiceDirectiveSource,
    VoiceDirectiveStatus,
    VoiceEmotion,
    VoiceEmphasisDirective,
    VoicePauseDirective,
    VoiceProviderPreferences,
)
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


registry = (
    VoiceProfileRegistryService
    .with_default_profiles()
)

validation_service = (
    VoiceDirectiveValidationService(
        voice_profile_registry=registry,
    )
)

resolution_service = (
    VoiceDirectiveResolutionService(
        voice_profile_registry=registry,
        validation_service=(
            validation_service
        ),
    )
)


narration = (
    "The ancient door slowly opened. "
    "No one knew what waited behind it. "
    "The name Derinkuyu had been forgotten."
)

directives = SceneVoiceDirectives(
    scene_number=1,
    voice_profile_id=(
        "voice.horror_whisper"
    ),
    language="English",
    language_code="en-US",
    emotion=VoiceEmotion.SUSPENSEFUL,
    speed=1.0,
    pause_before_seconds=0.2,
    pause_after_seconds=0.3,
    pronunciation_directives=[
        PronunciationDirective(
            text="Derinkuyu",
            pronunciation="de-rin-ku-yu",
        ),
    ],
    pause_directives=[
        VoicePauseDirective(
            after_text=(
                "The ancient door slowly opened."
            ),
            duration_seconds=0.8,
        ),
    ],
    emphasis_directives=[
        VoiceEmphasisDirective(
            text="No one",
            strength=0.8,
        ),
    ],
    provider_preferences=(
        VoiceProviderPreferences(
            preferred_provider="ElevenLabs",
            preferred_model=(
                "eleven_multilingual_v2"
            ),
            preferred_output_format="mp3",
        )
    ),
    source=(
        VoiceDirectiveSource.GENRE_PROFILE
    ),
    metadata={
        "genre_id": "genre.horror",
    },
)

blueprint = resolution_service.resolve(
    directives,
    narration_text=narration,
    scene_duration_seconds=30.0,
)

print("Status:", blueprint.status)
print(
    "Resolved profile:",
    blueprint.profile.resolved_profile_id,
)
print(
    "Estimated duration:",
    blueprint
    .estimated_speech_duration_seconds,
)

assert (
    blueprint.status
    == VoiceBlueprintResolutionStatus.RESOLVED
)

assert blueprint.is_resolved is True
assert blueprint.is_generation_ready is True

assert (
    blueprint.profile.resolved_profile_id
    == "voice.horror_whisper"
)

assert (
    blueprint.profile.found_exact_match
    is True
)

assert (
    blueprint.profile.used_fallback
    is False
)

assert (
    blueprint.narration_text
    == narration
)

assert blueprint.scene_number == 1
assert blueprint.language_code == "en-us"

assert (
    blueprint.explicit_instruction_count
    == 3
)

assert (
    blueprint.selected_provider_mapping[
        "model_id"
    ]
    == "eleven_multilingual_v2"
)

assert (
    directives.status
    == VoiceDirectiveStatus.READY
)

assert (
    blueprint.metadata[
        "genre_id"
    ]
    == "genre.horror"
)


fallback_directives = (
    SceneVoiceDirectives(
        scene_number=2,
        voice_profile_id=(
            "voice.not_registered"
        ),
    )
)

fallback_blueprint = (
    resolution_service.resolve(
        fallback_directives,
        narration_text=(
            "A short neutral narration."
        ),
        scene_duration_seconds=8.0,
    )
)

print(
    "Fallback profile:",
    fallback_blueprint
    .profile.resolved_profile_id,
)

assert (
    fallback_blueprint.status
    == VoiceBlueprintResolutionStatus
    .RESOLVED_WITH_FALLBACK
)

assert (
    fallback_blueprint
    .profile
    .resolved_profile_id
    == "voice.neutral_narrator"
)

assert (
    fallback_blueprint
    .profile
    .used_fallback
    is True
)

assert fallback_blueprint.warnings


generated_blueprint = (
    resolution_service.mark_generated(
        blueprint,
        output_file=(
            "outputs/audio/scene_001.mp3"
        ),
    )
)

assert (
    generated_blueprint.status
    == VoiceBlueprintResolutionStatus
    .GENERATED
)

assert (
    generated_blueprint.output_file
    == "outputs/audio/scene_001.mp3"
)

assert generated_blueprint.is_resolved is True
assert (
    generated_blueprint.is_generation_ready
    is False
)


many_results = (
    resolution_service.resolve_many(
        [
            (
                SceneVoiceDirectives(
                    scene_number=4,
                ),
                "Narration for scene four.",
                8.0,
            ),
            (
                SceneVoiceDirectives(
                    scene_number=3,
                ),
                "Narration for scene three.",
                8.0,
            ),
        ]
    )
)

assert [
    item.scene_number
    for item in many_results
] == [
    3,
    4,
]


invalid_directives = (
    SceneVoiceDirectives(
        scene_number=5,
        pause_directives=[
            VoicePauseDirective(
                after_text=(
                    "Text that does not exist"
                ),
                duration_seconds=1.0,
            )
        ],
    )
)

try:
    resolution_service.resolve(
        invalid_directives,
        narration_text=(
            "A valid narration without "
            "the requested reference."
        ),
        scene_duration_seconds=15.0,
    )
except ValueError:
    print(
        "Invalid voice directives "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Invalid voice directives should fail."
    )

assert (
    invalid_directives.status
    == VoiceDirectiveStatus.FAILED
)


long_narration = " ".join(
    ["word"] * 100
)

try:
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=6,
        ),
        narration_text=long_narration,
        scene_duration_seconds=10.0,
    )
except ValueError:
    print(
        "Voice timing overflow "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Narration exceeding scene duration "
        "should fail."
    )


try:
    resolution_service.resolve_many(
        [
            (
                SceneVoiceDirectives(
                    scene_number=7,
                ),
                "First narration.",
                8.0,
            ),
            (
                SceneVoiceDirectives(
                    scene_number=7,
                ),
                "Duplicate narration.",
                8.0,
            ),
        ]
    )
except ValueError:
    print(
        "Duplicate voice scenes "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Duplicate voice scenes should fail."
    )


serialized = (
    fallback_blueprint.model_dump_json()
)

restored = (
    fallback_blueprint.__class__
    .model_validate_json(
        serialized
    )
)

assert restored == fallback_blueprint


print(
    "Voice Directive Resolution Service "
    "tests completed successfully."
)