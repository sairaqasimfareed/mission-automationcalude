from __future__ import annotations

from src.models.elevenlabs_voice_request import (
    ElevenLabsVoiceRequest,
    ElevenLabsVoiceSettings,
)
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.voice_directives import VoiceEmotion, VoicePace
from src.services.voice_narration_markup_service import VoiceNarrationMarkupService

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
    pronunciation directives) has no verified ElevenLabs API surface
    backing it in this codebase's own testing (see
    ElevenLabsVoiceProvider's own docstring: "has not been verified
    against a live ElevenLabs account") - rather than fabricate an
    unverified mapping, this service names each one explicitly in
    `unsupported_controls` only when it actually holds a non-default,
    meaningful value, so a person can see exactly what would be lost
    without this being silently dropped or spuriously flagged on every
    call.

    pause_directives/emphasis_directives are the one exception: those
    DO have a real, documented ElevenLabs mechanism (text-based
    markup - ellipses for a pause, CAPITALIZATION for emphasis, no
    request-parameter equivalent for either), applied here via
    VoiceNarrationMarkupService directly onto the narration text
    before it's sent - real voice gaps #6/#7 from the 2026-09-09 audit.
    A directive that couldn't be located in the narration text still
    surfaces in `unsupported_controls` (its own targeted warning, not
    a generic "unsupported" label), so nothing is silently dropped.
    """

    def __init__(
        self,
        *,
        narration_markup_service: VoiceNarrationMarkupService | None = None,
    ) -> None:
        self._narration_markup_service = (
            narration_markup_service or VoiceNarrationMarkupService()
        )

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

        marked_up_text, markup_warnings = self._narration_markup_service.apply(
            blueprint.narration_text,
            pause_directives=blueprint.pause_directives,
            emphasis_directives=blueprint.emphasis_directives,
        )

        return ElevenLabsVoiceRequest(
            text=marked_up_text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings=voice_settings,
            unsupported_controls=[
                *self._unsupported_controls(blueprint),
                *markup_warnings,
            ],
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

        # pause_directives/emphasis_directives are no longer unsupported -
        # VoiceNarrationMarkupService applies both as real text markup
        # (see translate()). pause_before_seconds/pause_after_seconds are
        # a distinct concern (lead-in/lead-out silence around the whole
        # scene, applied downstream as an audio fade during mixing, not
        # an in-text pause) and remain genuinely unmapped here.
        if blueprint.pause_before_seconds or blueprint.pause_after_seconds:
            unsupported.append(
                "pause_before_seconds/pause_after_seconds (no verified "
                "ElevenLabs voice_settings equivalent - applied downstream "
                "as an audio fade during mixing, not an in-text pause)"
            )

        return unsupported
