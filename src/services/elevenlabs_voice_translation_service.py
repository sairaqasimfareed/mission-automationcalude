from __future__ import annotations

from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryLocator,
)
from src.models.elevenlabs_voice_request import (
    ElevenLabsVoiceRequest,
    ElevenLabsVoiceSettings,
)
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.voice_directives import VoiceDeliveryMode, VoiceEmotion, VoicePace
from src.services.voice_narration_markup_service import VoiceNarrationMarkupService

_DEFAULT_MODEL_ID = "eleven_multilingual_v2"

# ElevenLabs' real v3 model id - the only model supporting inline
# emotional audio tags, confirmed against ElevenLabs' own current
# documentation (2026-09-09). Used unconditionally whenever
# blueprint.voice_delivery_mode is EMOTION_TAGS, regardless of what
# model_id a caller passes - there is no legitimate reason to send a
# "[worried]"-style tag to any other model, which would just leak the
# literal bracketed text into the spoken narration instead of
# affecting delivery.
_V3_MODEL_ID = "eleven_v3"

# ElevenLabs' documented voice_settings.speed range - narrower than
# ResolvedVoiceBlueprint.speed's own 0.5-2.0, so a blueprint value
# outside this window is clamped, not rejected (an out-of-range speed
# request should degrade to "as close as the provider allows," not
# fail generation entirely).
_MIN_PROVIDER_SPEED = 0.7
_MAX_PROVIDER_SPEED = 1.2

# Voice gap #4 (2026-09-09 audit): every key here has a real,
# documented eleven_v3 example tag, verified directly against
# ElevenLabs' own current documentation and blog posts (not
# fabricated) - "[curious]", "[worried]", "[softly]", "[happily]",
# "[sad]", "[excited]", "[booming]", "[thoughtful]", "[awe]",
# "[sorrowful]" all appear as real, documented example tags.
# ElevenLabs' own guidance describes the tag vocabulary as open/
# non-exhaustive ("you can infer similar, contextually appropriate
# audio tags"), so this mapping is a defensible, real choice per
# emotion, not a closed enum ElevenLabs enforces - but every value
# used here is still one of their own documented examples, not an
# invented word. VoiceEmotion.NEUTRAL is deliberately absent - it is
# this codebase's own "no special direction" baseline, matching how
# it's already skipped everywhere else in this service.
_EMOTION_TAG_BY_EMOTION: dict[VoiceEmotion, str] = {
    VoiceEmotion.CALM: "softly",
    VoiceEmotion.WARM: "happily",
    VoiceEmotion.FRIENDLY: "happily",
    VoiceEmotion.SAD: "sad",
    VoiceEmotion.HAPPY: "happily",
    VoiceEmotion.EXCITED: "excited",
    VoiceEmotion.SUSPENSEFUL: "worried",
    VoiceEmotion.FEARFUL: "worried",
    VoiceEmotion.TENSE: "worried",
    VoiceEmotion.MYSTERIOUS: "curious",
    VoiceEmotion.AUTHORITATIVE: "booming",
    VoiceEmotion.SERIOUS: "thoughtful",
    VoiceEmotion.DRAMATIC: "awe",
    VoiceEmotion.INSPIRATIONAL: "awe",
    VoiceEmotion.EMOTIONAL: "sorrowful",
}


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

    pronunciation_directives is a second, real exception (voice gap
    #5) - but unlike voice_settings or text markup, a pronunciation
    dictionary must be CREATED via its own, separate ElevenLabs API
    call before a TTS request can reference it, which this pure/
    no-network service cannot do itself. The caller (the real,
    network-calling ElevenLabsVoiceProvider) is responsible for
    creating the dictionary first and passing its resolved locator in
    via `pronunciation_dictionary_locators` - when supplied and
    non-empty, pronunciation_directives is no longer flagged
    unsupported; omitting it (the default) reproduces this service's
    exact prior behavior.

    emotion is a third, conditional exception (voice gaps #4/#9/#10) -
    ElevenLabs' two real delivery mechanisms are mutually exclusive
    (confirmed against ElevenLabs' own documentation): eleven_v3
    supports inline emotional audio tags but not request stitching;
    eleven_multilingual_v2 (and similar) supports request stitching
    but has no audio-tag mechanism. `blueprint.voice_delivery_mode`
    (set per genre - see GenreVoiceProfile.voice_delivery_mode)
    decides which applies: EMOTION_TAGS forces `model_id` to the real
    "eleven_v3" regardless of what's passed in (any other model would
    just speak the literal bracketed tag text aloud) and prefixes a
    real, documented v3 example tag onto the narration when one exists
    for the blueprint's emotion; CONTINUITY_STITCHING instead populates
    `previous_text`/`next_text` from the blueprint's own
    previous/next-scene narration context (set by
    VoiceDirectiveResolutionService.resolve_many() from adjacent scene
    requests in the same batch).
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
        pronunciation_dictionary_locators: (
            list[ElevenLabsPronunciationDictionaryLocator] | None
        ) = None,
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

        resolved_model_id = model_id
        previous_text: str | None = None
        next_text: str | None = None
        emotion_tag_applied = False

        if blueprint.voice_delivery_mode == VoiceDeliveryMode.EMOTION_TAGS:
            resolved_model_id = _V3_MODEL_ID

            emotion_tag = _EMOTION_TAG_BY_EMOTION.get(blueprint.emotion)

            if emotion_tag:
                marked_up_text = f"[{emotion_tag}] {marked_up_text}"
                emotion_tag_applied = True
        else:
            previous_text = blueprint.previous_scene_narration_text
            next_text = blueprint.next_scene_narration_text

        resolved_locators = pronunciation_dictionary_locators or []

        return ElevenLabsVoiceRequest(
            text=marked_up_text,
            voice_id=voice_id,
            model_id=resolved_model_id,
            voice_settings=voice_settings,
            pronunciation_dictionary_locators=resolved_locators,
            previous_text=previous_text,
            next_text=next_text,
            unsupported_controls=[
                *self._unsupported_controls(
                    blueprint,
                    has_pronunciation_dictionary=bool(resolved_locators),
                    emotion_tag_applied=emotion_tag_applied,
                ),
                *markup_warnings,
            ],
        )

    @staticmethod
    def _unsupported_controls(
        blueprint: ResolvedVoiceBlueprint,
        *,
        has_pronunciation_dictionary: bool = False,
        emotion_tag_applied: bool = False,
    ) -> list[str]:
        unsupported: list[str] = []

        if blueprint.emotion != VoiceEmotion.NEUTRAL and not emotion_tag_applied:
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

        if blueprint.pronunciation_directives and not has_pronunciation_dictionary:
            unsupported.append(
                f"{len(blueprint.pronunciation_directives)} pronunciation "
                "directive(s) (no pronunciation dictionary was created/"
                "supplied for this request)"
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
