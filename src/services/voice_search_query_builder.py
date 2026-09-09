from __future__ import annotations

from src.models.voice_directives import VoiceEmotion
from src.models.voice_profile import VoiceProfile

_ELEVENLABS_PROVIDER_NAME = "elevenlabs"
_RECOMMENDED_TAGS_KEY = "recommended_voice_tags"


def build_voice_search_query(profile: VoiceProfile) -> str:
    """
    Build a real, honest free-text search query for ElevenLabs' voice
    search endpoint from one provider-independent VoiceProfile.

    ElevenLabs' `search` parameter matches free text against a real
    voice's name/description/labels/category (confirmed via their own
    current API documentation) - so this joins the profile's own
    provider_mappings["elevenlabs"]["recommended_voice_tags"]
    (already curated, real descriptive words like "deep"/"dark"/
    "whisper" - see VoiceProfileRegistryService) with its pitch_style
    and (non-neutral) emotion values, rather than hardcoding a mapping
    onto ElevenLabs' own structured gender/age/accent filters - this
    codebase has not verified the exact enum values those filters
    accept, and guessing would risk silently returning zero real
    matches instead of an honest, broad free-text search.

    Pure/deterministic - no network call. Returns an empty string only
    when a profile has no real tags and a fully default style (should
    not happen for any of this codebase's built-in profiles, but
    callers should treat an empty result as "nothing to search for"
    rather than searching ElevenLabs with a blank term).
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
    return " ".join(dict.fromkeys(terms))
