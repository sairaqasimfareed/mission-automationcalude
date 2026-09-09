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

registry = VoiceProfileRegistryService.with_default_profiles()

validation_service = VoiceDirectiveValidationService(
    voice_profile_registry=registry,
)

resolution_service = VoiceDirectiveResolutionService(
    voice_profile_registry=registry,
    validation_service=(validation_service),
)


narration = (
    "The ancient door slowly opened. "
    "No one knew what waited behind it. "
    "The name Derinkuyu had been forgotten."
)

directives = SceneVoiceDirectives(
    scene_number=1,
    voice_profile_id=("voice.horror_whisper"),
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
            after_text=("The ancient door slowly opened."),
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
            preferred_model=("eleven_multilingual_v2"),
            preferred_output_format="mp3",
        )
    ),
    source=(VoiceDirectiveSource.GENRE_PROFILE),
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
    blueprint.estimated_speech_duration_seconds,
)

assert blueprint.status == VoiceBlueprintResolutionStatus.RESOLVED

assert blueprint.is_resolved is True
assert blueprint.is_generation_ready is True

assert blueprint.profile.resolved_profile_id == "voice.horror_whisper"

assert blueprint.profile.found_exact_match is True

assert blueprint.profile.used_fallback is False

assert blueprint.narration_text == narration

assert blueprint.scene_number == 1
assert blueprint.language_code == "en-us"

assert blueprint.explicit_instruction_count == 3

assert blueprint.selected_provider_mapping["model_id"] == "eleven_multilingual_v2"

assert directives.status == VoiceDirectiveStatus.READY

assert blueprint.metadata["genre_id"] == "genre.horror"


fallback_directives = SceneVoiceDirectives(
    scene_number=2,
    voice_profile_id=("voice.not_registered"),
)

fallback_blueprint = resolution_service.resolve(
    fallback_directives,
    narration_text=("A short neutral narration."),
    scene_duration_seconds=8.0,
)

print(
    "Fallback profile:",
    fallback_blueprint.profile.resolved_profile_id,
)

assert (
    fallback_blueprint.status == VoiceBlueprintResolutionStatus.RESOLVED_WITH_FALLBACK
)

assert fallback_blueprint.profile.resolved_profile_id == "voice.neutral_narrator"

assert fallback_blueprint.profile.used_fallback is True

assert fallback_blueprint.warnings


generated_blueprint = resolution_service.mark_generated(
    blueprint,
    output_file=("outputs/audio/scene_001.mp3"),
)

assert generated_blueprint.status == VoiceBlueprintResolutionStatus.GENERATED

assert generated_blueprint.output_file == "outputs/audio/scene_001.mp3"

assert generated_blueprint.is_resolved is True
assert generated_blueprint.is_generation_ready is False


many_results = resolution_service.resolve_many(
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

assert [item.scene_number for item in many_results] == [
    3,
    4,
]


invalid_directives = SceneVoiceDirectives(
    scene_number=5,
    pause_directives=[
        VoicePauseDirective(
            after_text=("Text that does not exist"),
            duration_seconds=1.0,
        )
    ],
)

try:
    resolution_service.resolve(
        invalid_directives,
        narration_text=("A valid narration without " "the requested reference."),
        scene_duration_seconds=15.0,
    )
except ValueError:
    print("Invalid voice directives " "successfully blocked.")
else:
    raise AssertionError("Invalid voice directives should fail.")

assert invalid_directives.status == VoiceDirectiveStatus.FAILED


long_narration = " ".join(["word"] * 100)

try:
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=6,
        ),
        narration_text=long_narration,
        scene_duration_seconds=10.0,
    )
except ValueError:
    print("Voice timing overflow " "successfully blocked.")
else:
    raise AssertionError("Narration exceeding scene duration " "should fail.")


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
    print("Duplicate voice scenes " "successfully blocked.")
else:
    raise AssertionError("Duplicate voice scenes should fail.")


serialized = fallback_blueprint.model_dump_json()

restored = fallback_blueprint.__class__.model_validate_json(serialized)

assert restored == fallback_blueprint


# --- Voice gap #1 (2026-09-09 audit): target_provider reaches
# _select_provider_mapping even when the directive's own
# provider_preferences never set one - the real, ordinary
# genre-driven path. ---

no_preference_directives = SceneVoiceDirectives(
    scene_number=8,
    voice_profile_id="voice.horror_whisper",
)

assert no_preference_directives.provider_preferences.preferred_provider is None

no_target_blueprint = resolution_service.resolve(
    no_preference_directives,
    narration_text="A short narration.",
    scene_duration_seconds=8.0,
)

assert no_target_blueprint.selected_provider_mapping == {}

with_target_directives = SceneVoiceDirectives(
    scene_number=9,
    voice_profile_id="voice.horror_whisper",
)

with_target_blueprint = resolution_service.resolve(
    with_target_directives,
    narration_text="A short narration.",
    scene_duration_seconds=8.0,
    target_provider="elevenlabs",
)

assert with_target_blueprint.selected_provider_mapping["model_id"] == (
    "eleven_multilingual_v2"
)

print("target_provider reaches the real per-genre mapping.")


# --- A real, persisted voice_id from VoiceProviderMappingService
# overlays whatever the built-in profile's own provider_mappings
# carries (today: never a real voice_id, only recommended_voice_tags). ---

from src.services.registry.voice_provider_mapping_repository import (  # noqa: E402
    InMemoryVoiceProviderMappingRepository,
)
from src.services.voice_provider_mapping_service import (  # noqa: E402
    VoiceProviderMappingService,
)

mapping_service = VoiceProviderMappingService(
    repository=InMemoryVoiceProviderMappingRepository()
)
mapping_service.load()
mapping_service.set_voice_id(
    voice_profile_id="voice.horror_whisper",
    provider_name="elevenlabs",
    voice_id="real-horror-voice-42",
)

resolution_service_with_mapping = VoiceDirectiveResolutionService(
    voice_profile_registry=registry,
    validation_service=validation_service,
    voice_provider_mapping_service=mapping_service,
)

overlaid_blueprint = resolution_service_with_mapping.resolve(
    SceneVoiceDirectives(scene_number=10, voice_profile_id="voice.horror_whisper"),
    narration_text="A short narration.",
    scene_duration_seconds=8.0,
    target_provider="elevenlabs",
)

assert overlaid_blueprint.selected_provider_mapping["voice_id"] == (
    "real-horror-voice-42"
)
# The rest of the profile's own real mapping (model_id) survives the overlay.
assert overlaid_blueprint.selected_provider_mapping["model_id"] == (
    "eleven_multilingual_v2"
)

# An unregistered profile falls through untouched - no fabricated id.
unmapped_blueprint = resolution_service_with_mapping.resolve(
    SceneVoiceDirectives(
        scene_number=11, voice_profile_id="voice.documentary_authoritative"
    ),
    narration_text="A short narration.",
    scene_duration_seconds=8.0,
    target_provider="elevenlabs",
)

assert "voice_id" not in unmapped_blueprint.selected_provider_mapping

print("Real, persisted voice_id mapping overlays the resolved blueprint.")


# --- Voice gap #9 (2026-09-09 audit): real scene-to-scene stitching
# context, derived automatically by resolve_many() from genuinely
# adjacent scenes - regardless of input list order. ---

from src.models.voice_directives import VoiceDeliveryMode  # noqa: E402

stitched_blueprints = resolution_service.resolve_many(
    [
        # Deliberately out of order - resolve_many() must still derive
        # adjacency from scene_number, not input position.
        (
            SceneVoiceDirectives(
                scene_number=22,
                voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING,
            ),
            "Middle scene narration.",
            8.0,
        ),
        (
            SceneVoiceDirectives(
                scene_number=21,
                voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING,
            ),
            "First scene narration.",
            8.0,
        ),
        (
            SceneVoiceDirectives(
                scene_number=23,
                voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING,
            ),
            "Last scene narration.",
            8.0,
        ),
    ]
)

by_scene = {blueprint.scene_number: blueprint for blueprint in stitched_blueprints}

assert by_scene[21].previous_scene_narration_text is None
assert by_scene[21].next_scene_narration_text == "Middle scene narration."

assert by_scene[22].previous_scene_narration_text == "First scene narration."
assert by_scene[22].next_scene_narration_text == "Last scene narration."

assert by_scene[23].previous_scene_narration_text == "Middle scene narration."
assert by_scene[23].next_scene_narration_text is None

# A standalone resolve() call (no batch context) leaves both None.
standalone_blueprint = resolution_service.resolve(
    SceneVoiceDirectives(scene_number=24),
    narration_text="A standalone scene.",
    scene_duration_seconds=8.0,
)

assert standalone_blueprint.previous_scene_narration_text is None
assert standalone_blueprint.next_scene_narration_text is None

print("resolve_many() derives real stitching context from adjacent scenes.")


print("Voice Directive Resolution Service " "tests completed successfully.")
