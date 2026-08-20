from __future__ import annotations

from src.models.voice_directive_validation import (
    VoiceValidationCode,
)
from src.models.voice_directives import (
    PronunciationDirective,
    SceneVoiceDirectives,
    VoiceDirectiveStatus,
    VoiceEmphasisDirective,
    VoicePauseDirective,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)

registry = VoiceProfileRegistryService.with_default_profiles()

service = VoiceDirectiveValidationService(
    voice_profile_registry=registry,
    maximum_explicit_instructions=5,
)


narration = (
    "The ancient door slowly opened. "
    "No one knew what waited behind it. "
    "The name Derinkuyu had been forgotten."
)

valid_directives = SceneVoiceDirectives(
    scene_number=1,
    voice_profile_id="voice.horror_whisper",
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
            after_text=("The ancient door " "slowly opened."),
            duration_seconds=0.8,
        ),
    ],
    emphasis_directives=[
        VoiceEmphasisDirective(
            text="No one",
            strength=0.8,
        ),
    ],
)

valid_result = service.validate(
    valid_directives,
    narration_text=narration,
    scene_duration_seconds=30.0,
)

print(
    "Valid:",
    valid_result.is_valid,
)

print(
    "Generation ready:",
    valid_result.is_generation_ready,
)

print(
    "Estimated duration:",
    valid_result.estimated_speech_duration_seconds,
)

assert valid_result.is_valid is True
assert valid_result.is_generation_ready is True
assert valid_result.errors == []

assert valid_result.profile_reference is not None

assert valid_result.profile_reference.found_exact_match is True

assert valid_result.narration_word_count > 0

assert valid_result.explicit_instruction_count == 3


fallback_directives = SceneVoiceDirectives(
    scene_number=2,
    voice_profile_id=("voice.not_registered"),
)

fallback_result = service.validate(
    fallback_directives,
    narration_text="A neutral narration.",
    scene_duration_seconds=8.0,
)

assert fallback_result.is_valid is True
assert fallback_result.is_generation_ready is True

assert fallback_result.profile_reference is not None

assert fallback_result.profile_reference.used_fallback is True

assert any(
    issue.code == VoiceValidationCode.VOICE_PROFILE_FALLBACK_USED
    for issue in fallback_result.warnings
)


empty_result = service.validate(
    SceneVoiceDirectives(
        scene_number=3,
    ),
    narration_text="   ",
    scene_duration_seconds=8.0,
)

assert empty_result.is_valid is False
assert empty_result.is_generation_ready is False

assert any(
    issue.code == VoiceValidationCode.EMPTY_NARRATION for issue in empty_result.errors
)


invalid_reference_directives = SceneVoiceDirectives(
    scene_number=4,
    pause_directives=[
        VoicePauseDirective(
            after_text=("Text that is missing"),
            duration_seconds=1.0,
        ),
        VoicePauseDirective(
            at_character_index=999,
            duration_seconds=1.0,
        ),
    ],
    emphasis_directives=[
        VoiceEmphasisDirective(
            text="missing phrase",
        ),
    ],
)

invalid_reference_result = service.validate(
    invalid_reference_directives,
    narration_text="A short narration.",
    scene_duration_seconds=12.0,
)

assert invalid_reference_result.is_valid is False

assert any(
    issue.code == VoiceValidationCode.PAUSE_TEXT_NOT_FOUND
    for issue in invalid_reference_result.errors
)

assert any(
    issue.code == VoiceValidationCode.PAUSE_INDEX_OUT_OF_RANGE
    for issue in invalid_reference_result.errors
)

assert any(
    issue.code == VoiceValidationCode.EMPHASIS_TEXT_NOT_FOUND
    for issue in invalid_reference_result.errors
)


unused_pronunciation_result = service.validate(
    SceneVoiceDirectives(
        scene_number=5,
        pronunciation_directives=[
            PronunciationDirective(
                text="Derinkuyu",
                pronunciation="de-rin-ku-yu",
            )
        ],
    ),
    narration_text="A completely different sentence.",
    scene_duration_seconds=10.0,
)

assert unused_pronunciation_result.is_valid is True

assert any(
    issue.code == VoiceValidationCode.PRONUNCIATION_TEXT_NOT_FOUND
    for issue in (unused_pronunciation_result.warnings)
)


long_narration = " ".join(["word"] * 100)

duration_result = service.validate(
    SceneVoiceDirectives(
        scene_number=6,
        speed=1.0,
    ),
    narration_text=long_narration,
    scene_duration_seconds=10.0,
)

assert duration_result.is_valid is False

assert any(
    issue.code == VoiceValidationCode.SPEECH_EXCEEDS_SCENE
    for issue in duration_result.errors
)


short_narration_result = service.validate(
    SceneVoiceDirectives(
        scene_number=7,
    ),
    narration_text="Very short narration.",
    scene_duration_seconds=20.0,
)

assert short_narration_result.is_valid is True

assert any(
    issue.code == VoiceValidationCode.EXCESSIVE_SPEECH_GAP
    for issue in short_narration_result.warnings
)


updated_directives = SceneVoiceDirectives(
    scene_number=8,
)

updated_result = service.validate_and_update(
    updated_directives,
    narration_text=("This narration is valid."),
    scene_duration_seconds=8.0,
)

assert updated_result.is_valid is True

assert updated_directives.status == VoiceDirectiveStatus.READY


failed_directives = SceneVoiceDirectives(
    scene_number=9,
)

failed_result = service.validate_and_update(
    failed_directives,
    narration_text="",
    scene_duration_seconds=8.0,
)

assert failed_result.is_valid is False

assert failed_directives.status == VoiceDirectiveStatus.FAILED

assert failed_directives.warnings


print("Voice Directive Validation Service " "tests completed successfully.")
