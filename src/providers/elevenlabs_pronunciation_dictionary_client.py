from __future__ import annotations

import json

from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryLocator,
)
from src.models.voice_directives import PronunciationDirective
from src.services.elevenlabs_pronunciation_dictionary_translation_service import (
    ElevenLabsPronunciationDictionaryTranslationService,
)
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)

_DEFAULT_BASE_URL = "https://api.elevenlabs.io"
_DEFAULT_TIMEOUT_SECONDS = 60.0


class ElevenLabsPronunciationDictionaryClient:
    """
    Real ElevenLabs pronunciation-dictionary HTTP client.

    Calls POST /v1/pronunciation-dictionaries/add-from-rules to create
    a real pronunciation dictionary from a set of rules, returning the
    locator (dictionary id + version id) ElevenLabs' text-to-speech
    endpoint needs to actually apply it via
    `pronunciation_dictionary_locators`.

    This is the real fix for voice gap #5 from the 2026-09-09 audit:
    the pronunciation-directive content VoiceDirectiveContentGenerationService
    already produces (gap #11) had nowhere real to go -
    ElevenLabsVoiceTranslationService's own docstring already
    disclaimed no verified pronunciation-directive mapping existed,
    since a pronunciation dictionary must be created via its own,
    separate API call before a TTS request can reference it (unlike
    voice_settings, which is inline on the TTS request itself).

    Built from ElevenLabs' documented API shape. Not yet verified
    against a real, live ElevenLabs account - the same disclosed,
    honest limitation as ElevenLabsVoiceProvider's own docstring for
    the TTS endpoint itself.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        transport: Transport | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        translation_service: (
            ElevenLabsPronunciationDictionaryTranslationService | None
        ) = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport or default_transport
        self._timeout_seconds = timeout_seconds
        self._translation_service = (
            translation_service or ElevenLabsPronunciationDictionaryTranslationService()
        )

    def create_from_directives(
        self,
        directives: list[PronunciationDirective],
        *,
        name: str,
    ) -> ElevenLabsPronunciationDictionaryLocator:
        if not directives:
            raise ValueError(
                "Cannot create a pronunciation dictionary with no directives."
            )

        rules = self._translation_service.translate(directives)

        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/pronunciation-dictionaries/add-from-rules",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body={
                "name": name,
                "rules": [
                    rule.model_dump(
                        exclude_none=True, exclude={"id", "created_at", "updated_at"}
                    )
                    for rule in rules
                ],
            },
            timeout_seconds=self._timeout_seconds,
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                "ElevenLabs pronunciation-dictionary creation failed with "
                f"HTTP {response.status_code}."
            )

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpProviderExecutionError(
                "ElevenLabs pronunciation-dictionary creation returned a "
                "non-JSON response."
            ) from error

        dictionary_id = payload.get("id")
        version_id = payload.get("version_id")

        if not dictionary_id or not version_id:
            raise HttpProviderExecutionError(
                "ElevenLabs pronunciation-dictionary creation response was "
                "missing id/version_id."
            )

        return ElevenLabsPronunciationDictionaryLocator(
            pronunciation_dictionary_id=dictionary_id,
            version_id=version_id,
        )
