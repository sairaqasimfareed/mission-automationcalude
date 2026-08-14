from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.models.provider_profile import ProviderProfile
from src.providers.voice_provider import VoiceProvider
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)

_DEFAULT_BASE_URL = "https://api.elevenlabs.io"
_DEFAULT_MODEL_ID = "eleven_multilingual_v2"
_DEFAULT_OUTPUT_DIRECTORY = Path("data/voice_output")


class ElevenLabsVoiceProvider(VoiceProvider):
    """
    Real ElevenLabs text-to-speech adapter.

    Calls POST /v1/text-to-speech/{voice_id} with an xi-api-key header
    and a JSON body, expecting a raw audio/mpeg response - the shape
    documented in ElevenLabs' TTS API. This has not been verified
    against a live ElevenLabs account (no real API key exists in this
    environment yet); confirm the endpoint path, model_id value, and
    response format against current ElevenLabs docs once a real key
    is available.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
        output_directory: str | Path = _DEFAULT_OUTPUT_DIRECTORY,
        model_id: str = _DEFAULT_MODEL_ID,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._transport = transport or default_transport
        self._output_directory = Path(output_directory)
        self._model_id = model_id
        self._base_url = (profile.base_url or _DEFAULT_BASE_URL).rstrip("/")

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def health_check(self) -> bool:
        return True

    def generate_voice(self, text: str, voice: str) -> str:
        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/text-to-speech/{voice}",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body={"text": text, "model_id": self._model_id},
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
