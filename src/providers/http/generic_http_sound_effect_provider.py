from __future__ import annotations

from pathlib import Path

from src.models.http_adapter_config import HttpResponseMode
from src.models.provider_profile import ProviderProfile
from src.providers.sound_effect_provider import SoundEffectProvider
from src.services.http.http_provider_executor import HttpProviderExecutor

_DEFAULT_OUTPUT_DIRECTORY = Path("data/sound_effect_output")
_DEFAULT_AUDIO_EXTENSION = ".mp3"

_SUPPORTED_RESPONSE_MODES = {
    HttpResponseMode.BINARY_FILE,
    HttpResponseMode.JSON_FILE_URL,
}


class GenericHttpSoundEffectProvider(SoundEffectProvider):
    """
    No-code SoundEffectProvider, driven entirely by a ProviderProfile's
    http_adapter_config.

    Same shape as GenericHttpVoiceProvider, resolving a single
    {library_query} placeholder.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        executor: HttpProviderExecutor | None = None,
        output_directory: str | Path = _DEFAULT_OUTPUT_DIRECTORY,
    ) -> None:
        if profile.http_adapter_config is None:
            raise ValueError(
                f"Provider profile '{profile.profile_id}' has no "
                "http_adapter_config; GenericHttpSoundEffectProvider "
                "requires one."
            )

        if profile.http_adapter_config.response_mode not in _SUPPORTED_RESPONSE_MODES:
            raise ValueError(
                f"Provider profile '{profile.profile_id}' has "
                f"response_mode={profile.http_adapter_config.response_mode.value}, "
                "but a sound-effect provider must use binary_file or "
                "json_file_url."
            )

        self._profile = profile
        self._config = profile.http_adapter_config
        self._api_key = api_key
        self._executor = executor or HttpProviderExecutor()
        self._output_directory = output_directory

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def health_check(self) -> bool:
        return True

    def generate_sound_effect(self, *, library_query: str) -> str:
        response = self._executor.execute(
            self._config,
            placeholders={"library_query": library_query},
            api_key=self._api_key,
            base_url=self._profile.base_url,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        if self._config.response_mode == HttpResponseMode.BINARY_FILE:
            return self._executor.extract_binary_file(
                response,
                destination_directory=self._output_directory,
                default_extension=_DEFAULT_AUDIO_EXTENSION,
                config=self._config,
            )

        file_url = self._executor.extract_json_file_url(response, self._config)

        return self._executor.download_to_file(
            file_url,
            destination_directory=self._output_directory,
            default_extension=_DEFAULT_AUDIO_EXTENSION,
            timeout_seconds=float(self._profile.timeout_seconds),
        )
