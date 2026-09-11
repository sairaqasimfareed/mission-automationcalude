from __future__ import annotations

from src.models.elevenlabs_voice_search import ElevenLabsVoiceSearchResult
from src.models.voice_directives import VoiceEmotion, VoicePitchStyle
from src.models.voice_profile import VoiceProfile
from src.services.dynamic_voice_selection_service import DynamicVoiceSelectionService
from src.services.http.http_provider_executor import HttpProviderExecutionError


class _StubSearchClient:
    """
    Duck-typed stand-in for ElevenLabsVoiceSearchClient.suggest() -
    only the method DynamicVoiceSelectionService actually calls.
    """

    def __init__(
        self,
        *,
        results: list[ElevenLabsVoiceSearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.results = results if results is not None else []
        self.error = error
        self.calls: list[list[str]] = []

    def suggest(
        self,
        *,
        terms: list[str],
        page_size_per_term: int = 5,
        max_results: int = 5,
    ) -> list[ElevenLabsVoiceSearchResult]:
        self.calls.append(list(terms))

        if self.error is not None:
            raise self.error

        return self.results


def _profile(**overrides: object) -> VoiceProfile:
    defaults: dict[str, object] = {
        "profile_id": "voice.test_horror",
        "display_name": "Test Horror",
        "fallback_profile_id": "voice.neutral_narrator",
        "pitch_style": VoicePitchStyle.DEEP,
        "emotion": VoiceEmotion.SUSPENSEFUL,
        "provider_mappings": {
            "elevenlabs": {"recommended_voice_tags": ["dark", "whisper"]},
        },
    }
    defaults.update(overrides)

    return VoiceProfile(**defaults)  # type: ignore[arg-type]


def _result(voice_id: str) -> ElevenLabsVoiceSearchResult:
    return ElevenLabsVoiceSearchResult(voice_id=voice_id, name=voice_id)


def test_select_voice_id_returns_the_top_real_candidate() -> None:
    client = _StubSearchClient(results=[_result("voice-a"), _result("voice-b")])
    service = DynamicVoiceSelectionService(search_client=client)  # type: ignore[arg-type]

    voice_id = service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.SUSPENSEFUL,
        pitch_style=VoicePitchStyle.DEEP,
    )

    assert voice_id == "voice-a"


def test_select_voice_id_passes_the_directive_style_not_only_the_profile_default() -> (
    None
):
    client = _StubSearchClient(results=[_result("voice-a")])
    service = DynamicVoiceSelectionService(search_client=client)  # type: ignore[arg-type]

    service.select_voice_id(
        profile=_profile(
            pitch_style=VoicePitchStyle.DEEP, emotion=VoiceEmotion.NEUTRAL
        ),
        emotion=VoiceEmotion.EXCITED,
        pitch_style=VoicePitchStyle.BRIGHT,
    )

    assert "bright" in client.calls[0]
    assert "excited" in client.calls[0]
    assert "deep" not in client.calls[0]


def test_select_voice_id_returns_none_when_no_candidates_found() -> None:
    client = _StubSearchClient(results=[])
    service = DynamicVoiceSelectionService(search_client=client)  # type: ignore[arg-type]

    voice_id = service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.SUSPENSEFUL,
        pitch_style=VoicePitchStyle.DEEP,
    )

    assert voice_id is None


def test_select_voice_id_returns_none_on_a_real_search_failure_instead_of_raising() -> (
    None
):
    client = _StubSearchClient(
        error=HttpProviderExecutionError("ElevenLabs voice search failed.")
    )
    service = DynamicVoiceSelectionService(search_client=client)  # type: ignore[arg-type]

    voice_id = service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.SUSPENSEFUL,
        pitch_style=VoicePitchStyle.DEEP,
    )

    assert voice_id is None


def test_select_voice_id_caches_by_profile_emotion_and_pitch_style() -> None:
    client = _StubSearchClient(results=[_result("voice-a")])
    service = DynamicVoiceSelectionService(search_client=client)  # type: ignore[arg-type]

    first = service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.SUSPENSEFUL,
        pitch_style=VoicePitchStyle.DEEP,
    )
    second = service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.SUSPENSEFUL,
        pitch_style=VoicePitchStyle.DEEP,
    )

    assert first == second == "voice-a"
    assert len(client.calls) == 1


def test_select_voice_id_does_not_cache_across_different_styles() -> None:
    client = _StubSearchClient(results=[_result("voice-a")])
    service = DynamicVoiceSelectionService(search_client=client)  # type: ignore[arg-type]

    service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.SUSPENSEFUL,
        pitch_style=VoicePitchStyle.DEEP,
    )
    service.select_voice_id(
        profile=_profile(),
        emotion=VoiceEmotion.EXCITED,
        pitch_style=VoicePitchStyle.BRIGHT,
    )

    assert len(client.calls) == 2
