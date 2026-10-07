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
    describe_http_failure,
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

    Verified against a real, live ElevenLabs account (2026-09-08):
    both generate_music() and generate_sound_effect() produced real,
    non-empty MP3 files end to end through this exact class - the
    endpoint path, xi-api-key header, JSON body shape, and
    audio/mpeg response handling are all confirmed correct, not just
    documented-and-hoped.
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
                describe_http_failure("ElevenLabs sound-generation request", response)
            )

        self._output_directory.mkdir(parents=True, exist_ok=True)
        destination = self._output_directory / f"{uuid4()}.mp3"
        destination.write_bytes(response.content)

        return str(destination.resolve())

    def compose(self, *, prompt: str, duration_seconds: float) -> str:
        """One instrumental track of the requested length from /v1/music."""

        milliseconds = int(round(duration_seconds * 1000))

        if not _MIN_COMPOSED_MUSIC_MS <= milliseconds <= _MAX_COMPOSED_MUSIC_MS:
            raise ValueError(
                "ElevenLabs composes music between 3 seconds and 10 minutes long; "
                f"{duration_seconds:.0f} seconds was requested."
            )

        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/music",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body={
                "prompt": prompt,
                "music_length_ms": milliseconds,
                "force_instrumental": True,
            },
            timeout_seconds=max(float(self._profile.timeout_seconds), 300.0),
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                describe_http_failure("ElevenLabs music composition request", response)
            )

        self._output_directory.mkdir(parents=True, exist_ok=True)
        destination = self._output_directory / f"{uuid4()}.mp3"
        destination.write_bytes(response.content)

        return str(destination.resolve())


# ElevenLabs' music composition endpoint (POST /v1/music): a prompt and a length of
# 3 s to 10 min. Separate from the sound-generation endpoint above, which only makes
# short clips (about 30 s at most) and is why music used to be several short pieces.
_MIN_COMPOSED_MUSIC_MS = 3_000
_MAX_COMPOSED_MUSIC_MS = 600_000


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

    def generate_composed_music(self, *, prompt: str, duration_seconds: float) -> str:
        return self._core.compose(prompt=prompt, duration_seconds=duration_seconds)


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
