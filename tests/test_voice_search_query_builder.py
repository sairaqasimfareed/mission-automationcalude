from __future__ import annotations

from src.models.voice_directives import VoiceEmotion, VoicePitchStyle
from src.models.voice_profile import VoiceProfile
from src.services.voice_profile_registry_service import VoiceProfileRegistryService
from src.services.voice_search_query_builder import build_voice_search_terms


def _registry() -> VoiceProfileRegistryService:
    return VoiceProfileRegistryService.with_default_profiles()


def test_build_terms_uses_recommended_tags() -> None:
    profile = _registry().get("voice.horror_whisper")

    terms = build_voice_search_terms(profile)

    assert "deep" in terms
    assert "dark" in terms
    assert "whisper" in terms


def test_build_terms_includes_pitch_style() -> None:
    profile = _registry().get("voice.horror_whisper")

    terms = build_voice_search_terms(profile)

    assert VoicePitchStyle.DEEP.value in terms


def test_build_terms_includes_non_neutral_emotion() -> None:
    profile = _registry().get("voice.horror_whisper")

    terms = build_voice_search_terms(profile)

    assert profile.emotion != VoiceEmotion.NEUTRAL
    assert profile.emotion.value in terms


def test_build_terms_excludes_neutral_emotion() -> None:
    profile = _registry().get("voice.neutral_narrator")

    assert profile.emotion == VoiceEmotion.NEUTRAL

    terms = build_voice_search_terms(profile)

    assert "neutral" not in terms


def test_build_terms_deduplicates_an_exact_repeated_term() -> None:
    profile = VoiceProfile(
        profile_id="voice.test_dedupe",
        display_name="Test Dedupe",
        fallback_profile_id="voice.neutral_narrator",
        pitch_style=VoicePitchStyle.DEEP,
        provider_mappings={
            "elevenlabs": {
                "recommended_voice_tags": ["deep", "resonant"],
            }
        },
    )

    terms = build_voice_search_terms(profile)

    # "deep" appears once from recommended_voice_tags and would
    # otherwise be re-added for pitch_style=DEEP ("deep") too.
    assert terms.count("deep") == 1


def test_build_terms_returns_each_term_individually_not_joined() -> None:
    profile = _registry().get("voice.horror_whisper")

    terms = build_voice_search_terms(profile)

    # Each real term stays its own list entry - a caller (e.g.
    # ElevenLabsVoiceSearchClient.suggest()) is responsible for
    # searching them one at a time, never joined into one compound
    # phrase (verified live: ElevenLabs' search only matches a
    # compound phrase that appears together, literally, in a voice's
    # name - joining terms reliably returns zero real matches).
    assert all(" " not in term for term in terms)


def test_build_terms_returns_no_terms_for_an_empty_style_profile() -> None:
    profile = VoiceProfile(
        profile_id="voice.test_empty_style",
        display_name="Test Empty Style",
        fallback_profile_id="voice.neutral_narrator",
    )

    terms = build_voice_search_terms(profile)

    # Default pitch_style ("natural") is still a real, single term -
    # only emotion is excluded by default (NEUTRAL).
    assert terms == [VoicePitchStyle.NATURAL.value]


def test_build_terms_ignores_a_provider_mapping_for_a_different_provider() -> None:
    profile = VoiceProfile(
        profile_id="voice.test_other_provider",
        display_name="Test Other Provider",
        fallback_profile_id="voice.neutral_narrator",
        provider_mappings={
            "openai": {"recommended_voice_tags": ["should-not-appear"]},
        },
    )

    terms = build_voice_search_terms(profile)

    assert "should-not-appear" not in terms
