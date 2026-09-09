from __future__ import annotations

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_directives import (
    PronunciationDirective,
    VoiceDeliveryMode,
    VoiceEmotion,
    VoiceEmphasisDirective,
    VoicePace,
    VoicePauseDirective,
)
from src.services.elevenlabs_voice_translation_service import (
    ElevenLabsVoiceTranslationService,
)


def _blueprint(**overrides: object) -> ResolvedVoiceBlueprint:
    base: dict[str, object] = dict(
        scene_number=1,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.neutral_narrator",
            resolved_profile_id="voice.neutral_narrator",
            display_name="Neutral Narrator",
        ),
        narration_text="The Mary Celeste was found adrift in 1872.",
    )
    base.update(overrides)
    # **dict unpacking against a pydantic model's constructor is a
    # known mypy-plugin limitation (this session's own established
    # accepted-debt pattern) - suppressed here once rather than
    # re-litigated per field.
    return ResolvedVoiceBlueprint(**base)  # type: ignore[arg-type]


def test_translate_maps_documented_voice_settings_fields() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(stability=0.6, similarity_boost=0.8, style_strength=0.2),
        voice_id="voice-abc",
    )

    assert request.voice_settings.stability == 0.6
    assert request.voice_settings.similarity_boost == 0.8
    assert request.voice_settings.style == 0.2
    assert request.voice_settings.use_speaker_boost is True
    assert request.voice_id == "voice-abc"
    assert request.text == "The Mary Celeste was found adrift in 1872."


def test_translate_clamps_speed_to_provider_range() -> None:
    service = ElevenLabsVoiceTranslationService()

    fast_request = service.translate(_blueprint(speed=2.0), voice_id="voice-abc")
    slow_request = service.translate(_blueprint(speed=0.5), voice_id="voice-abc")

    assert fast_request.voice_settings.speed == 1.2
    assert slow_request.voice_settings.speed == 0.7


def test_translate_with_defaults_has_no_unsupported_controls() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(_blueprint(), voice_id="voice-abc")

    assert request.unsupported_controls == []


def test_translate_flags_non_default_emotion_as_unsupported() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(emotion=VoiceEmotion.EMOTIONAL), voice_id="voice-abc"
    )

    assert any("emotion" in control for control in request.unsupported_controls)


def test_translate_flags_non_default_pace_as_unsupported() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(_blueprint(pace=VoicePace.FAST), voice_id="voice-abc")

    assert any("pace" in control for control in request.unsupported_controls)


def test_translate_flags_pronunciation_directives_as_unsupported() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            pronunciation_directives=[
                PronunciationDirective(text="Celeste", pronunciation="seh-LEST")
            ]
        ),
        voice_id="voice-abc",
    )

    assert any("pronunciation" in control for control in request.unsupported_controls)


def test_translate_flags_pause_before_seconds_as_unsupported() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(pause_before_seconds=1.5), voice_id="voice-abc"
    )

    assert any("pause" in control for control in request.unsupported_controls)


def test_translate_applies_emphasis_directive_as_capitalization() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            emphasis_directives=[VoiceEmphasisDirective(text="found", strength=0.8)]
        ),
        voice_id="voice-abc",
    )

    assert "FOUND" in request.text
    assert "found" not in request.text
    assert not any("emphasis" in control for control in request.unsupported_controls)


def test_translate_applies_pause_directive_as_text_markup() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            pause_directives=[
                VoicePauseDirective(after_text="adrift", duration_seconds=1.0)
            ]
        ),
        voice_id="voice-abc",
    )

    assert "adrift" in request.text
    assert "…" in request.text
    assert request.text.index("…") > request.text.index("adrift")
    assert not any(
        "pause directive" in control for control in request.unsupported_controls
    )


def test_translate_flags_unmatched_emphasis_directive_as_unsupported() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            emphasis_directives=[
                VoiceEmphasisDirective(text="not in the narration", strength=0.5)
            ]
        ),
        voice_id="voice-abc",
    )

    assert any(
        "not found in narration" in control for control in request.unsupported_controls
    )


def test_translate_uses_default_model_id() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(_blueprint(), voice_id="voice-abc")

    assert request.model_id == "eleven_multilingual_v2"


def test_translate_accepts_custom_model_id() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(), voice_id="voice-abc", model_id="eleven_turbo_v2"
    )

    assert request.model_id == "eleven_turbo_v2"


# --- Voice gaps #4/#9/#10 (2026-09-09 audit): emotion tags vs.
# request stitching, mutually exclusive per ElevenLabs' real API. ---


def test_translate_emotion_tags_mode_forces_the_real_v3_model() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            voice_delivery_mode=VoiceDeliveryMode.EMOTION_TAGS,
            emotion=VoiceEmotion.SUSPENSEFUL,
        ),
        voice_id="voice-abc",
        model_id="eleven_turbo_v2",
    )

    assert request.model_id == "eleven_v3"


def test_translate_emotion_tags_mode_prefixes_a_real_tag() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            voice_delivery_mode=VoiceDeliveryMode.EMOTION_TAGS,
            emotion=VoiceEmotion.SUSPENSEFUL,
        ),
        voice_id="voice-abc",
    )

    assert request.text.startswith("[worried] ")
    assert not any("emotion" in control for control in request.unsupported_controls)


def test_translate_emotion_tags_mode_with_neutral_emotion_applies_no_tag() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            voice_delivery_mode=VoiceDeliveryMode.EMOTION_TAGS,
            emotion=VoiceEmotion.NEUTRAL,
        ),
        voice_id="voice-abc",
    )

    assert request.model_id == "eleven_v3"
    assert not request.text.startswith("[")
    assert request.text == _blueprint().narration_text


def test_translate_continuity_stitching_mode_still_flags_emotion() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING,
            emotion=VoiceEmotion.SUSPENSEFUL,
        ),
        voice_id="voice-abc",
    )

    assert request.model_id != "eleven_v3"
    assert any("emotion" in control for control in request.unsupported_controls)


def test_translate_continuity_stitching_mode_populates_previous_and_next_text() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING,
            previous_scene_narration_text="The crew boarded at dawn.",
            next_scene_narration_text="No trace of them was ever found.",
        ),
        voice_id="voice-abc",
    )

    assert request.previous_text == "The crew boarded at dawn."
    assert request.next_text == "No trace of them was ever found."


def test_translate_continuity_stitching_mode_without_neighbors_leaves_text_none() -> (
    None
):
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING),
        voice_id="voice-abc",
    )

    assert request.previous_text is None
    assert request.next_text is None


def test_translate_emotion_tags_mode_ignores_stitching_context() -> None:
    service = ElevenLabsVoiceTranslationService()

    request = service.translate(
        _blueprint(
            voice_delivery_mode=VoiceDeliveryMode.EMOTION_TAGS,
            previous_scene_narration_text="The crew boarded at dawn.",
            next_scene_narration_text="No trace of them was ever found.",
        ),
        voice_id="voice-abc",
    )

    assert request.previous_text is None
    assert request.next_text is None
