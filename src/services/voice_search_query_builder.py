from __future__ import annotations

from src.models.voice_directives import VoiceEmotion
from src.models.voice_profile import VoiceProfile

_ELEVENLABS_PROVIDER_NAME = "elevenlabs"
_RECOMMENDED_TAGS_KEY = "recommended_voice_tags"


def build_voice_search_terms(profile: VoiceProfile) -> list[str]:
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

    Pure/deterministic - no network call.
    """

    provider_mapping = profile.provider_mappings.get(_ELEVENLABS_PROVIDER_NAME, {})
    recommended_tags = provider_mapping.get(_RECOMMENDED_TAGS_KEY, [])

    terms: list[str] = [
        str(tag).strip() for tag in recommended_tags if str(tag).strip()
    ]

    pitch_style = profile.pitch_style.value

    if pitch_style not in terms:
        terms.append(pitch_style)

    if profile.emotion != VoiceEmotion.NEUTRAL and profile.emotion.value not in terms:
        terms.append(profile.emotion.value)

    # dict.fromkeys preserves first-seen order while deduping.
    return list(dict.fromkeys(terms))
