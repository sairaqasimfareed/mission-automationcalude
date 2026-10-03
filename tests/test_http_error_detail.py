"""
HTTP failure detail, 2026-10-03: a live voiceover failed with only "ElevenLabs
text-to-speech request failed with HTTP 401." - but ElevenLabs returns 401 for
a wrong key, a key missing a permission, AND exhausted credits, and the body
that says which was thrown away. The reason is now part of the error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.elevenlabs_sound_generation_provider import (
    ElevenLabsMusicProvider,
    ElevenLabsSoundEffectProvider,
)
from src.providers.elevenlabs_voice_provider import ElevenLabsVoiceProvider
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    HttpTransportResponse,
    PreparedHttpRequest,
    describe_http_failure,
    summarize_error_response,
)

_SECRET = "sk_this_must_never_appear_in_an_error"


def _response(body: object, status: int = 401) -> HttpTransportResponse:
    content = body if isinstance(body, bytes) else json.dumps(body).encode()

    return HttpTransportResponse(status_code=status, headers={}, content=content)


class TestSummarizeErrorResponse:
    def test_elevenlabs_style_dict_detail_gives_status_and_message(self) -> None:
        body = {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}

        assert summarize_error_response(_response(body)) == (
            "invalid_api_key: Invalid API key"
        )

    @pytest.mark.parametrize(
        ("status", "message"),
        [
            (
                "missing_permissions",
                "The API key is missing the text_to_speech permission.",
            ),
            ("quota_exceeded", "You have exceeded your character quota."),
        ],
    )
    def test_the_other_401_reasons_are_told_apart(
        self, status: str, message: str
    ) -> None:
        body = {"detail": {"status": status, "message": message}}

        assert summarize_error_response(_response(body)).startswith(status)

    def test_a_plain_string_detail(self) -> None:
        assert (
            summarize_error_response(_response({"detail": "Not found"})) == "Not found"
        )

    def test_a_validation_error_list_uses_the_first_message(self) -> None:
        body = {"detail": [{"loc": ["body", "text"], "msg": "field required"}]}

        assert summarize_error_response(_response(body)) == "field required"

    def test_a_non_json_body_is_shown_trimmed(self) -> None:
        assert summarize_error_response(_response(b"  unauthorized \n")) == (
            "unauthorized"
        )

    def test_an_empty_body_gives_nothing(self) -> None:
        assert summarize_error_response(_response(b"")) == ""

    def test_invalid_utf8_does_not_raise(self) -> None:
        assert isinstance(summarize_error_response(_response(b"\xff\xfe bad")), str)

    def test_a_long_reason_is_truncated(self) -> None:
        reason = summarize_error_response(_response({"detail": "x" * 1000}))

        assert len(reason) == 240
        assert reason.endswith("...")


class TestDescribeHttpFailure:
    def test_includes_the_reason_in_brackets(self) -> None:
        message = describe_http_failure(
            "ElevenLabs text-to-speech request",
            _response(
                {"detail": {"status": "quota_exceeded", "message": "No credits"}}
            ),
        )

        assert message == (
            "ElevenLabs text-to-speech request failed with HTTP 401 "
            "(quota_exceeded: No credits)."
        )

    def test_without_a_reason_it_is_exactly_the_old_message(self) -> None:
        assert describe_http_failure("X request", _response(b"", status=500)) == (
            "X request failed with HTTP 500."
        )


class _Transport:
    def __init__(self, response: HttpTransportResponse) -> None:
        self._response = response
        self.requests: list[PreparedHttpRequest] = []

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.requests.append(request)

        return self._response


def _profile(category: ProviderCategory) -> ProviderProfile:
    return ProviderProfile(
        profile_id="profile-1",
        display_name="Profile One",
        provider_name="elevenlabs",
        category=category,
    )


_BAD_KEY = _response(
    {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}
)


def test_a_voice_401_names_its_reason_and_never_leaks_the_key(tmp_path: Path) -> None:
    provider = ElevenLabsVoiceProvider(
        profile=_profile(ProviderCategory.VOICE),
        api_key=_SECRET,
        transport=_Transport(_BAD_KEY),
        output_directory=str(tmp_path),
    )

    with pytest.raises(HttpProviderExecutionError) as error:
        provider.generate_voice("Hello.", "voice-id")

    assert "HTTP 401 (invalid_api_key: Invalid API key)" in str(error.value)
    assert _SECRET not in str(error.value)


def test_a_sound_effect_401_names_its_reason(tmp_path: Path) -> None:
    provider = ElevenLabsSoundEffectProvider(
        profile=_profile(ProviderCategory.SOUND_EFFECTS),
        api_key=_SECRET,
        transport=_Transport(_BAD_KEY),
        output_directory=str(tmp_path),
    )

    with pytest.raises(HttpProviderExecutionError) as error:
        provider.generate_sound_effect(library_query="door creak")

    assert "invalid_api_key" in str(error.value)
    assert _SECRET not in str(error.value)


def test_a_music_401_names_its_reason(tmp_path: Path) -> None:
    provider = ElevenLabsMusicProvider(
        profile=_profile(ProviderCategory.MUSIC),
        api_key=_SECRET,
        transport=_Transport(_BAD_KEY),
        output_directory=str(tmp_path),
    )

    with pytest.raises(HttpProviderExecutionError) as error:
        provider.generate_music(library_query="calm piano", duration_seconds=10.0)

    assert "invalid_api_key" in str(error.value)
