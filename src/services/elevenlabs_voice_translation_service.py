from __future__ import annotations

from src.models.elevenlabs_voice_request import (
    ElevenLabsVoiceRequest,
    ElevenLabsVoiceSettings,
)
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.voice_directives import VoiceEmotion, VoicePace

_DEFAULT_MODEL_ID = "eleven_multilingual_v2"

# ElevenLabs' documented voice_settings.speed range - narrower than
# ResolvedVoiceBlueprint.speed's own 0.5-2.0, so a blueprint value
# outside this window is clamped, not rejected (an out-of-range speed
# request should degrade to "as close as the provider allows," not
# fail generation entirely).
_MIN_PROVIDER_SPEED = 0.7
_MAX_PROVIDER_SPEED = 1.2


class ElevenLabsVoiceTranslationService:
    """
    Post-Script-Approval Production Plan, Phase 9: "Add an ElevenLabs
    translator mapping every supported blueprint property into
    provider settings and safe fallback for unsupported controls."

    Pure/deterministic - no LLM call, no network call. Maps only
    ResolvedVoiceBlueprint fields with a genuinely documented
    ElevenLabs `voice_settings` equivalent (stability, similarity_boost,
    style, use_speaker_boost, speed). Every other rich control the
    blueprint carries (emotion, pace, pitch_adjustment, volume_gain_db,
    pronunciation/pause/emphasis directives) has no verified ElevenLabs
    API surface backing it in this codebase's own testing (see
    ElevenLabsVoiceProvider's own docstring: "has not been verified
    against a live ElevenLabs account") - rather than fabricate an
    unverified mapping (e.g. inserting speculative SSML-like tags into
    the narration text), this service names each one explicitly in
    `unsupported_controls` only when it actually holds a non-default,
    meaningful value, so a person can see exactly what would be lost
    without this being silently dropped or spuriously flagged on every
    call.
    """

    def translate(
        self,
        blueprint: ResolvedVoiceBlueprint,
        *,
        voice_id: str,
        model_id: str = _DEFAULT_MODEL_ID,
    ) -> ElevenLabsVoiceRequest:
        clamped_speed = max(
            _MIN_PROVIDER_SPEED, min(_MAX_PROVIDER_SPEED, blueprint.speed)
        )

        voice_settings = ElevenLabsVoiceSettings(
            stability=blueprint.stability,
            similarity_boost=blueprint.similarity_boost,
            style=blueprint.style_strength,
            use_speaker_boost=blueprint.speaker_boost,
            speed=clamped_speed,
        )

        return ElevenLabsVoiceRequest(
            text=blueprint.narration_text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings=voice_settings,
            unsupported_controls=self._unsupported_controls(blueprint),
        )

    @staticmethod
    def _unsupported_controls(blueprint: ResolvedVoiceBlueprint) -> list[str]:
        unsupported: list[str] = []

        if blueprint.emotion != VoiceEmotion.NEUTRAL:
            unsupported.append(
                f"emotion={blueprint.emotion.value} (no verified ElevenLabs "
                "voice_settings equivalent)"
            )

        if blueprint.pace != VoicePace.MODERATE:
            unsupported.append(
                f"pace={blueprint.pace.value} (partially covered by speed, "
                "not a full pacing control)"
            )

        if blueprint.pitch_adjustment != 0.0:
            unsupported.append(
                f"pitch_adjustment={blueprint.pitch_adjustment} (no verified "
                "ElevenLabs voice_settings equivalent)"
            )

        if blueprint.volume_gain_db != 0.0:
            unsupported.append(
                f"volume_gain_db={blueprint.volume_gain_db} (no verified "
                "ElevenLabs voice_settings equivalent)"
            )

        if blueprint.pronunciation_directives:
            unsupported.append(
                f"{len(blueprint.pronunciation_directives)} pronunciation "
                "directive(s) (no verified ElevenLabs text-markup equivalent)"
            )

        if (
            blueprint.pause_directives
            or blueprint.pause_before_seconds
            or (blueprint.pause_after_seconds)
        ):
            unsupported.append(
                "pause directive(s) (no verified ElevenLabs text-markup " "equivalent)"
            )

        if blueprint.emphasis_directives:
            unsupported.append(
                f"{len(blueprint.emphasis_directives)} emphasis directive(s) "
                "(no verified ElevenLabs text-markup equivalent)"
            )

        return unsupported
