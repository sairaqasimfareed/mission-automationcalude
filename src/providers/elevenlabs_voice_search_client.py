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

    `search()` is the thin, direct real API call for one query -
    `suggest()` (verified live 2026-09-10 against a real account) is
    the real method a caller building a style-based suggestion should
    use instead, since ElevenLabs' search only matches a whole
    compound phrase against a voice's literal name, not the
    fuzzy/labels-aware matching this codebase originally assumed from
    documentation alone.
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

    def suggest(
        self,
        *,
        terms: list[str],
        page_size_per_term: int = _DEFAULT_PAGE_SIZE,
        max_results: int = _DEFAULT_PAGE_SIZE,
    ) -> list[ElevenLabsVoiceSearchResult]:
        """
        Suggest real candidate voices for a list of individual search
        terms (see build_voice_search_terms()) - real fix for
        ElevenLabs' verified-live search behavior: `search` matches a
        voice's real `name` field literally and requires the whole
        query to appear together, so one compound multi-word query
        (e.g. "deep dark whisper suspenseful") reliably matches
        nothing, while individual real terms ("deep", "whisper") do.

        Runs one real search per term, merges results by voice_id, and
        ranks by how many distinct terms matched that voice - a voice
        matched by more of a profile's real style terms is a stronger
        real candidate than one matched by only one. Ties keep
        first-seen order (Python's sort is stable).

        Returns an empty list, with no real network call, when terms
        is empty - matching build_voice_search_terms()'s own honest
        "nothing to search for" contract.
        """

        if not terms:
            return []

        hit_counts: dict[str, int] = {}
        results_by_voice_id: dict[str, ElevenLabsVoiceSearchResult] = {}

        for term in terms:
            for result in self.search(query=term, page_size=page_size_per_term):
                hit_counts[result.voice_id] = hit_counts.get(result.voice_id, 0) + 1

                if result.voice_id not in results_by_voice_id:
                    results_by_voice_id[result.voice_id] = result

        ranked_voice_ids = sorted(
            results_by_voice_id,
            key=lambda voice_id: hit_counts[voice_id],
            reverse=True,
        )

        return [
            results_by_voice_id[voice_id] for voice_id in ranked_voice_ids[:max_results]
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
