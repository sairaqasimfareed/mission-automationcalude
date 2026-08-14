from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from src.models.provider_profile import ProviderProfile
from src.providers.music_provider import MusicProvider
from src.providers.sound_effect_provider import SoundEffectProvider
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)

_DEFAULT_BASE_URL = "https://api.elevenlabs.io"
_MUSIC_OUTPUT_DIRECTORY = Path("data/music_output")
_SOUND_EFFECT_OUTPUT_DIRECTORY = Path("data/sound_effect_output")


class _ElevenLabsSoundGenerationCore:
    """
    Shared ElevenLabs sound-generation HTTP call.

    ElevenLabs exposes one generative-audio endpoint (POST
    /v1/sound-generation, xi-api-key header, JSON body, raw audio/mpeg
    response) used for both background music and short sound effects
    - the only difference is whether a target duration is supplied.
    Not yet verified against a live account; confirm the endpoint path
    and payload shape against current ElevenLabs docs once a real key
    is available.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
        output_directory: str | Path,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._transport = transport or default_transport
        self._output_directory = Path(output_directory)
        self._base_url = (profile.base_url or _DEFAULT_BASE_URL).rstrip("/")

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def generate(self, *, prompt: str, duration_seconds: float | None) -> str:
        body: dict[str, Any] = {"text": prompt}

        if duration_seconds is not None:
            body["duration_seconds"] = duration_seconds

        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/sound-generation",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body=body,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"ElevenLabs sound-generation request failed with HTTP "
                f"{response.status_code}."
            )

        self._output_directory.mkdir(parents=True, exist_ok=True)
        destination = self._output_directory / f"{uuid4()}.mp3"
        destination.write_bytes(response.content)

        return str(destination.resolve())


class ElevenLabsMusicProvider(MusicProvider):
    """MusicProvider wrapper over ElevenLabs' shared sound-generation call."""

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
        output_directory: str | Path = _MUSIC_OUTPUT_DIRECTORY,
    ) -> None:
        self._core = _ElevenLabsSoundGenerationCore(
            profile=profile,
            api_key=api_key,
            transport=transport,
            output_directory=output_directory,
        )

    @property
    def provider_name(self) -> str:
        return self._core.provider_name

    def health_check(self) -> bool:
        return True

    def generate_music(self, *, library_query: str, duration_seconds: float) -> str:
        return self._core.generate(
            prompt=library_query, duration_seconds=duration_seconds
        )


class ElevenLabsSoundEffectProvider(SoundEffectProvider):
    """SoundEffectProvider wrapper over ElevenLabs' shared sound-generation call."""

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
        output_directory: str | Path = _SOUND_EFFECT_OUTPUT_DIRECTORY,
    ) -> None:
        self._core = _ElevenLabsSoundGenerationCore(
            profile=profile,
            api_key=api_key,
            transport=transport,
            output_directory=output_directory,
        )

    @property
    def provider_name(self) -> str:
        return self._core.provider_name

    def health_check(self) -> bool:
        return True

    def generate_sound_effect(self, *, library_query: str) -> str:
        return self._core.generate(prompt=library_query, duration_seconds=None)
