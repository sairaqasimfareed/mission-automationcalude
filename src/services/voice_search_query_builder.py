from __future__ import annotations

from src.models.voice_directives import VoiceEmotion, VoicePitchStyle
from src.models.voice_profile import VoiceProfile

_ELEVENLABS_PROVIDER_NAME = "elevenlabs"
_RECOMMENDED_TAGS_KEY = "recommended_voice_tags"


def build_voice_search_terms(
    profile: VoiceProfile,
    *,
    emotion: VoiceEmotion | None = None,
    pitch_style: VoicePitchStyle | None = None,
) -> list[str]:
    """
    Build the real, individual search terms to run against ElevenLabs'
    voice search endpoint for one provider-independent VoiceProfile.

    Verified live (2026-09-10) against a real ElevenLabs account, not
    assumed from documentation: `search` matches a real voice's `name`
    field literally and requires the whole query to appear together -
    a compound phrase like "deep dark whisper suspenseful" matched
    zero real voices, while single real terms like "deep" correctly
    found real matches ("Charlie - Deep, Confident, Energetic",
    "Brian - Deep, Resonant and Comforting"). An earlier version of
    this function joined every term into one query string, which is
    what surfaced this - corrected once the real behavior was known,
    not guessed at again.

    Returns each real term separately (recommended_voice_tags, plus
    pitch_style, plus any non-neutral emotion) so the real caller
    (ElevenLabsVoiceSearchClient.suggest()) can run one real search
    per term and merge/rank results - the only strategy confirmed live
    to actually surface matches for a profile's stylistic tags, which
    rarely appear together, verbatim, in a premade voice's name.

    emotion/pitch_style default to the profile's own static baseline
    (profile.emotion/profile.pitch_style) exactly as before -
    overriding them is the real fix for "don't hardcode a voice per
    genre": DynamicVoiceSelectionService passes the *resolved scene
    directive's* actual emotion/pitch_style (often LLM-produced, and
    free to differ scene-to-scene) instead of the profile's fixed
    default, so the real voice ElevenLabs suggests can legitimately
    vary by what the LLM actually asked for, not just by genre.

    Pure/deterministic - no network call.
    """

    provider_mapping = profile.provider_mappings.get(_ELEVENLABS_PROVIDER_NAME, {})
    recommended_tags = provider_mapping.get(_RECOMMENDED_TAGS_KEY, [])

    terms: list[str] = [
        str(tag).strip() for tag in recommended_tags if str(tag).strip()
    ]

    effective_pitch_style = (pitch_style or profile.pitch_style).value

    if effective_pitch_style not in terms:
        terms.append(effective_pitch_style)

    effective_emotion = emotion or profile.emotion

    if (
        effective_emotion != VoiceEmotion.NEUTRAL
        and effective_emotion.value not in terms
    ):
        terms.append(effective_emotion.value)

    # dict.fromkeys preserves first-seen order while deduping.
    return list(dict.fromkeys(terms))
