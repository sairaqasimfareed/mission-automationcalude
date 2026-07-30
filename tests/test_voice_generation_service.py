from __future__ import annotations

from src.models.audio_track import (
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.resolved_voice_blueprint import (
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_directives import (
    SceneVoiceDirectives,
    VoiceProviderPreferences,
)
from src.models.voice_generation import (
    VoiceGenerationFailureReason,
    VoiceGenerationStatus,
)
from src.providers.voice_provider import (
    VoiceProvider,
)
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


class DummyVoiceProvider(VoiceProvider):
    """Healthy dry-run provider."""

    @property
    def provider_name(self) -> str:
        return "Dummy Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        assert text
        assert voice

        return "outputs/audio/generated_scene.wav"


class UnhealthyVoiceProvider(VoiceProvider):
    """Provider that fails its health check."""

    @property
    def provider_name(self) -> str:
        return "Unhealthy Voice"

    def health_check(self) -> bool:
        return False

    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        raise AssertionError(
            "Unhealthy provider should not run."
        )


class FailingVoiceProvider(VoiceProvider):
    """Provider that raises during generation."""

    @property
    def provider_name(self) -> str:
        return "Failing Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        raise ConnectionError(
            "Simulated provider failure."
        )


class InvalidFormatVoiceProvider(VoiceProvider):
    """Provider returning an unsupported file format."""

    @property
    def provider_name(self) -> str:
        return "Invalid Format Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        return "outputs/audio/generated_scene.exe"


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
        validation_service=validation_service,
    )
)


directives = SceneVoiceDirectives(
    scene_number=1,
    voice_profile_id=(
        "voice.horror_whisper"
    ),
    provider_preferences=(
        VoiceProviderPreferences(
            preferred_provider="Dummy Voice",
            preferred_voice_id=(
                "dummy-horror-voice"
            ),
            preferred_output_format="wav",
        )
    ),
)

blueprint = resolution_service.resolve(
    directives,
    narration_text=(
        "The ancient doorway slowly opened "
        "into complete darkness."
    ),
    scene_duration_seconds=15.0,
)

service = VoiceGenerationService(
    providers=[
        DummyVoiceProvider(),
    ]
)

result = service.generate(
    blueprint,
    start_time_seconds=2.5,
)

print("Success:", result.success)
print("Provider:", result.provider)
print("Output:", result.output_file)

assert result.success is True

assert (
    result.status
    == VoiceGenerationStatus.COMPLETED
)

assert result.provider == "Dummy Voice"

assert (
    result.output_file
    == "outputs/audio/generated_scene.wav"
)

assert result.audio_track is not None

assert (
    result.audio_track.track_type
    == AudioTrackType.VOICEOVER
)

assert (
    result.audio_track.status
    == AudioTrackStatus.READY
)

assert (
    result.audio_track.start_time_seconds
    == 2.5
)

assert (
    result.audio_track.provider
    == "Dummy Voice"
)

assert (
    result.audio_track.metadata[
        "scene_number"
    ]
    == 1
)

assert (
    blueprint.status
    == VoiceBlueprintResolutionStatus
    .GENERATED
)

assert (
    blueprint.output_file
    == "outputs/audio/generated_scene.wav"
)


available = service.available_providers()

assert available == [
    "Dummy Voice",
]


unhealthy_service = VoiceGenerationService(
    providers=[
        UnhealthyVoiceProvider(),
    ]
)

unhealthy_blueprint = (
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=2,
        ),
        narration_text=(
            "Narration for unhealthy provider."
        ),
        scene_duration_seconds=12.0,
    )
)

unhealthy_result = (
    unhealthy_service.generate(
        unhealthy_blueprint,
    )
)

assert unhealthy_result.success is False

assert (
    unhealthy_result.failure
    is not None
)

assert (
    unhealthy_result.failure.reason
    == VoiceGenerationFailureReason
    .NO_PROVIDER_AVAILABLE
)


failing_service = VoiceGenerationService(
    providers=[
        FailingVoiceProvider(),
    ]
)

failing_blueprint = (
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=3,
        ),
        narration_text=(
            "Narration for failing provider."
        ),
        scene_duration_seconds=12.0,
    )
)

failing_result = failing_service.generate(
    failing_blueprint,
)

assert failing_result.success is False
assert failing_result.failure is not None

assert (
    failing_result.failure.reason
    == VoiceGenerationFailureReason
    .PROVIDER_ERROR
)

assert failing_result.attempts == 1


invalid_format_service = (
    VoiceGenerationService(
        providers=[
            InvalidFormatVoiceProvider(),
        ]
    )
)

invalid_format_blueprint = (
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=4,
        ),
        narration_text=(
            "Narration for invalid output format."
        ),
        scene_duration_seconds=12.0,
    )
)

invalid_format_result = (
    invalid_format_service.generate(
        invalid_format_blueprint,
    )
)

assert invalid_format_result.success is False

assert (
    invalid_format_result.failure
    is not None
)

assert (
    invalid_format_result.failure.reason
    == VoiceGenerationFailureReason
    .UNSUPPORTED_OUTPUT_FORMAT
)


unknown_provider_blueprint = (
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=5,
        ),
        narration_text=(
            "Narration for unknown provider."
        ),
        scene_duration_seconds=12.0,
    )
)

unknown_provider_result = service.generate(
    unknown_provider_blueprint,
    provider_name="Unknown Voice",
)

assert unknown_provider_result.success is False

assert (
    unknown_provider_result.failure
    is not None
)

assert (
    unknown_provider_result.failure.reason
    == VoiceGenerationFailureReason
    .NO_PROVIDER_AVAILABLE
)


many_blueprints = [
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=7,
        ),
        narration_text=(
            "Narration for scene seven."
        ),
        scene_duration_seconds=10.0,
    ),
    resolution_service.resolve(
        SceneVoiceDirectives(
            scene_number=6,
        ),
        narration_text=(
            "Narration for scene six."
        ),
        scene_duration_seconds=10.0,
    ),
]

many_results = service.generate_many(
    many_blueprints,
)

assert [
    item.scene_number
    for item in many_results
] == [
    6,
    7,
]

assert all(
    item.success
    for item in many_results
)

assert (
    many_results[0]
    .audio_track
    is not None
)

assert (
    many_results[1]
    .audio_track
    is not None
)

first_track = many_results[0].audio_track
second_track = many_results[1].audio_track

assert first_track is not None
assert second_track is not None

assert (
    second_track.start_time_seconds
    == (
        first_track.start_time_seconds
        + first_track.duration_seconds
    )
)


try:
    service.generate_many(
        [
            many_blueprints[0],
            many_blueprints[0],
        ]
    )
except ValueError:
    print(
        "Duplicate voice generation scenes "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Duplicate voice blueprint scenes "
        "should fail."
    )


try:
    service.generate(
        resolution_service.resolve(
            SceneVoiceDirectives(
                scene_number=8,
            ),
            narration_text=(
                "Narration with invalid start."
            ),
            scene_duration_seconds=10.0,
        ),
        start_time_seconds=-1.0,
    )
except ValueError:
    print(
        "Negative voice start time "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Negative voice start time should fail."
    )


print(
    "Voice Generation Service tests "
    "completed successfully."
)