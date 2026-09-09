from __future__ import annotations

import json

from src.models.elevenlabs_voice_search import ElevenLabsVoiceSearchResult
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)

_DEFAULT_BASE_URL = "https://api.elevenlabs.io"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_PAGE_SIZE = 5


class ElevenLabsVoiceSearchClient:
    """
    Real ElevenLabs voice-search HTTP client (GET /v2/voices,
    verified directly against ElevenLabs' own current API
    documentation, 2026-09-09).

    Real fix for "should this app suggest a voice per profile
    automatically" - the user explicitly chose auto-suggest-then-
    confirm over fully automatic or fully manual, since matching a
    voice's real *sound* to a genre is a judgment call this codebase
    has no way to make on its own (no audio playback/analysis exists
    here); this client finds real, plausible candidates by real
    metadata, a person still picks and confirms one.

    Built on the same injectable-Transport pattern every other
    ElevenLabs-calling service in this codebase already uses, so it
    shares the exact same fake-transport testing approach.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        transport: Transport | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport or default_transport
        self._timeout_seconds = timeout_seconds

    def search(
        self,
        *,
        query: str,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> list[ElevenLabsVoiceSearchResult]:
        cleaned_query = query.strip()

        if not cleaned_query:
            raise ValueError("A voice search query cannot be empty.")

        request = PreparedHttpRequest(
            method="GET",
            url=f"{self._base_url}/v2/voices",
            headers={
                "xi-api-key": self._api_key,
            },
            params={
                "search": cleaned_query,
                "page_size": str(page_size),
            },
            timeout_seconds=self._timeout_seconds,
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"ElevenLabs voice search failed with HTTP " f"{response.status_code}."
            )

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpProviderExecutionError(
                "ElevenLabs voice search returned a non-JSON response."
            ) from error

        if not isinstance(payload, dict):
            raise HttpProviderExecutionError(
                "ElevenLabs voice search response was not a JSON object."
            )

        raw_voices = payload.get("voices", [])

        if not isinstance(raw_voices, list):
            raise HttpProviderExecutionError(
                "ElevenLabs voice search response was missing a real " "'voices' array."
            )

        return [
            self._parse_voice(raw_voice)
            for raw_voice in raw_voices
            if isinstance(raw_voice, dict) and raw_voice.get("voice_id")
        ]

    @staticmethod
    def _parse_voice(raw_voice: dict[str, object]) -> ElevenLabsVoiceSearchResult:
        labels = raw_voice.get("labels")

        return ElevenLabsVoiceSearchResult(
            voice_id=str(raw_voice["voice_id"]),
            name=str(raw_voice.get("name") or ""),
            category=str(raw_voice.get("category") or ""),
            labels=labels if isinstance(labels, dict) else {},
            description=str(raw_voice.get("description") or ""),
            preview_url=(
                str(raw_voice["preview_url"]) if raw_voice.get("preview_url") else None
            ),
        )
