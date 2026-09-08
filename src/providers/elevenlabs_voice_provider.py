from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.models.provider_profile import ProviderProfile
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.providers.voice_provider import VoiceProvider
from src.services.elevenlabs_voice_translation_service import (
    ElevenLabsVoiceTranslationService,
)
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)
from src.services.voice_generation_service import VoiceGenerationService

_DEFAULT_BASE_URL = "https://api.elevenlabs.io"
_DEFAULT_MODEL_ID = "eleven_multilingual_v2"
_DEFAULT_OUTPUT_DIRECTORY = Path("data/voice_output")


class ElevenLabsVoiceProvider(VoiceProvider):
    """
    Real ElevenLabs text-to-speech adapter.

    Calls POST /v1/text-to-speech/{voice_id} with an xi-api-key header
    and a JSON body, expecting a raw audio/mpeg response - the shape
    documented in ElevenLabs' TTS API.

    Partially verified against a real, live ElevenLabs account
    (2026-09-08): a real call with a valid key reached ElevenLabs and
    got back a real HTTP 402 (Payment Required, insufficient
    text-to-speech credit on that account) rather than a 401/404 or a
    malformed-request error - the endpoint path, auth header, and
    request shape are confirmed accepted by ElevenLabs. The actual
    success response (audio/mpeg body) is still unconfirmed pending
    an account with real TTS credit; re-verify generate_voice()/
    generate_from_blueprint() end to end once one is available.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
        output_directory: str | Path = _DEFAULT_OUTPUT_DIRECTORY,
        model_id: str = _DEFAULT_MODEL_ID,
        translation_service: ElevenLabsVoiceTranslationService | None = None,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._transport = transport or default_transport
        self._output_directory = Path(output_directory)
        self._model_id = model_id
        self._base_url = (profile.base_url or _DEFAULT_BASE_URL).rstrip("/")
        # Post-Script-Approval Production Plan, Phase 9.
        self._translation_service = (
            translation_service or ElevenLabsVoiceTranslationService()
        )

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def health_check(self) -> bool:
        return True

    def generate_voice(self, text: str, voice: str) -> str:
        return self._call_text_to_speech(
            voice_id=voice,
            json_body={"text": text, "model_id": self._model_id},
        )

    def generate_from_blueprint(self, blueprint: ResolvedVoiceBlueprint) -> str:
        """
        Post-Script-Approval Production Plan, Phase 9: "The voice
        provider must consume a translated ResolvedVoiceBlueprint
        rather than only raw narration text." Overrides the base
        class's plain-text fallback with a real translation - every
        supported blueprint property ElevenLabsVoiceTranslationService
        can map becomes part of the request; everything it can't is
        simply absent from `voice_settings` rather than silently lost
        without a trace (see that service's own `unsupported_controls`
        list, carried on the returned request for a caller to log or
        surface).
        """

        voice_id = VoiceGenerationService.resolve_provider_voice(blueprint=blueprint)
        request = self._translation_service.translate(
            blueprint, voice_id=voice_id, model_id=self._model_id
        )

        return self._call_text_to_speech(
            voice_id=request.voice_id,
            json_body={
                "text": request.text,
                "model_id": request.model_id,
                "voice_settings": request.voice_settings.model_dump(),
            },
        )

    def _call_text_to_speech(
        self, *, voice_id: str, json_body: dict[str, object]
    ) -> str:
        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body=json_body,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"ElevenLabs text-to-speech request failed with HTTP "
                f"{response.status_code}."
            )

        self._output_directory.mkdir(parents=True, exist_ok=True)
        destination = self._output_directory / f"{uuid4()}.mp3"
        destination.write_bytes(response.content)

        return str(destination.resolve())
