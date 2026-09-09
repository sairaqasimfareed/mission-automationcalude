from __future__ import annotations

from src.models.voice_directives import VoiceEmotion, VoicePitchStyle
from src.models.voice_profile import VoiceProfile
from src.services.voice_profile_registry_service import VoiceProfileRegistryService
from src.services.voice_search_query_builder import build_voice_search_query


def _registry() -> VoiceProfileRegistryService:
    return VoiceProfileRegistryService.with_default_profiles()


def test_build_query_uses_recommended_tags() -> None:
    profile = _registry().get("voice.horror_whisper")

    query = build_voice_search_query(profile)

    assert "deep" in query
    assert "dark" in query
    assert "whisper" in query


def test_build_query_includes_pitch_style() -> None:
    profile = _registry().get("voice.horror_whisper")

    query = build_voice_search_query(profile)

    assert VoicePitchStyle.DEEP.value in query


def test_build_query_includes_non_neutral_emotion() -> None:
    profile = _registry().get("voice.horror_whisper")

    query = build_voice_search_query(profile)

    assert profile.emotion != VoiceEmotion.NEUTRAL
    assert profile.emotion.value in query


def test_build_query_excludes_neutral_emotion() -> None:
    profile = _registry().get("voice.neutral_narrator")

    assert profile.emotion == VoiceEmotion.NEUTRAL

    query = build_voice_search_query(profile)

    assert "neutral" not in query


def test_build_query_deduplicates_an_exact_repeated_term() -> None:
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

    query = build_voice_search_query(profile)

    # "deep" appears once from recommended_voice_tags and would
    # otherwise be re-added for pitch_style=DEEP ("deep") too.
    assert query.split().count("deep") == 1


def test_build_query_has_no_leading_or_trailing_whitespace() -> None:
    profile = _registry().get("voice.horror_whisper")

    query = build_voice_search_query(profile)

    assert query == query.strip()


def test_build_query_ignores_a_provider_mapping_for_a_different_provider() -> None:
    profile = VoiceProfile(
        profile_id="voice.test_other_provider",
        display_name="Test Other Provider",
        fallback_profile_id="voice.neutral_narrator",
        provider_mappings={
            "openai": {"recommended_voice_tags": ["should-not-appear"]},
        },
    )

    query = build_voice_search_query(profile)

    assert "should-not-appear" not in query
