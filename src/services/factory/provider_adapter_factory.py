from __future__ import annotations

from typing import NamedTuple, Protocol, TypeVar

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.elevenlabs_sound_generation_provider import (
    ElevenLabsMusicProvider,
    ElevenLabsSoundEffectProvider,
)
from src.providers.elevenlabs_voice_provider import ElevenLabsVoiceProvider
from src.providers.envato_stock_provider import EnvatoStockProvider
from src.providers.http.generic_http_music_provider import GenericHttpMusicProvider
from src.providers.http.generic_http_sound_effect_provider import (
    GenericHttpSoundEffectProvider,
)
from src.providers.http.generic_http_stock_provider import GenericHttpStockProvider
from src.providers.http.generic_http_voice_provider import GenericHttpVoiceProvider
from src.providers.music_provider import MusicProvider
from src.providers.pexels_stock_provider import PexelsStockProvider
from src.providers.pixabay_stock_provider import PixabayStockProvider
from src.providers.sound_effect_provider import SoundEffectProvider
from src.providers.voice_provider import VoiceProvider
from src.services.secrets.provider_secret_manager import ProviderSecretManager
from src.services.stock_search_service import StockProviderAdapter
from src.shared.logger import logger

_ProviderT = TypeVar("_ProviderT", covariant=True)


class _CodedAdapterConstructor(Protocol[_ProviderT]):
    """Shape every coded adapter class must match to register below."""

    def __call__(self, *, profile: ProviderProfile, api_key: str) -> _ProviderT: ...


# Coded (vendor-specific) adapters register themselves here per category,
# keyed by lower-cased provider_name. A profile in one of these
# categories whose provider_name doesn't match falls through to its
# generic HTTP adapter, or is inert if it has no http_adapter_config
# either.
_CODED_VOICE: dict[str, _CodedAdapterConstructor[VoiceProvider]] = {
    "elevenlabs": ElevenLabsVoiceProvider,
}
_CODED_MUSIC: dict[str, _CodedAdapterConstructor[MusicProvider]] = {
    "elevenlabs": ElevenLabsMusicProvider,
}
_CODED_SOUND_EFFECTS: dict[str, _CodedAdapterConstructor[SoundEffectProvider]] = {
    "elevenlabs": ElevenLabsSoundEffectProvider,
}
_CODED_STOCK: dict[str, _CodedAdapterConstructor[StockProviderAdapter]] = {
    "pexels": PexelsStockProvider,
    "pixabay": PixabayStockProvider,
    "envato": EnvatoStockProvider,
}


class ProviderAdapterBuildReport(NamedTuple):
    """Real adapter instances built from a set of provider profiles."""

    voice_providers: list[VoiceProvider]
    music_providers: list[MusicProvider]
    sound_effect_providers: list[SoundEffectProvider]
    stock_video_providers: list[StockProviderAdapter]
    stock_image_providers: list[StockProviderAdapter]
    warnings: list[str]


class ProviderAdapterFactory:
    """
    Turn configured, usable ProviderProfiles into real adapter instances.

    Separate from the existing LLM-only ProviderFactory
    (src/services/factory/provider_factory.py) - that one stays
    LLM-focused; this one covers VOICE/MUSIC/SOUND_EFFECTS/STOCK_VIDEO/
    STOCK_IMAGE, the categories that previously had no path from a
    configured ProviderProfile to a working adapter at all.

    Dispatch per profile: a coded (vendor-specific) adapter if
    provider_name matches a known name for that category, else a
    GenericHttp* adapter if http_adapter_config is set, else the
    profile is inert - reported as a warning rather than raised, so one
    misconfigured profile never breaks application startup. LLM/VIDEO/
    IMAGE/UPLOAD profiles are silently skipped; they are out of scope
    for this factory (LLM already has its own construction path).
    """

    def __init__(self, *, secret_manager: ProviderSecretManager) -> None:
        self._secret_manager = secret_manager

    def build(self, profiles: list[ProviderProfile]) -> ProviderAdapterBuildReport:
        voice_providers: list[VoiceProvider] = []
        music_providers: list[MusicProvider] = []
        sound_effect_providers: list[SoundEffectProvider] = []
        stock_video_providers: list[StockProviderAdapter] = []
        stock_image_providers: list[StockProviderAdapter] = []
        warnings: list[str] = []

        for profile in profiles:
            if not profile.usable:
                continue

            try:
                self._dispatch_one(
                    profile,
                    voice_providers=voice_providers,
                    music_providers=music_providers,
                    sound_effect_providers=sound_effect_providers,
                    stock_video_providers=stock_video_providers,
                    stock_image_providers=stock_image_providers,
                    warnings=warnings,
                )
            except Exception as error:  # noqa: BLE001 - isolate one bad profile
                warnings.append(
                    f"Provider profile '{profile.profile_id}' "
                    f"({profile.category.value}/{profile.provider_name}) "
                    f"could not be built: {type(error).__name__}: {error}"
                )

        for warning in warnings:
            logger.warning(warning)

        return ProviderAdapterBuildReport(
            voice_providers=voice_providers,
            music_providers=music_providers,
            sound_effect_providers=sound_effect_providers,
            stock_video_providers=stock_video_providers,
            stock_image_providers=stock_image_providers,
            warnings=warnings,
        )

    def _dispatch_one(
        self,
        profile: ProviderProfile,
        *,
        voice_providers: list[VoiceProvider],
        music_providers: list[MusicProvider],
        sound_effect_providers: list[SoundEffectProvider],
        stock_video_providers: list[StockProviderAdapter],
        stock_image_providers: list[StockProviderAdapter],
        warnings: list[str],
    ) -> None:
        if profile.category == ProviderCategory.VOICE:
            coded_voice = _CODED_VOICE.get(self._normalized_name(profile))

            if coded_voice is not None:
                voice_providers.append(
                    coded_voice(profile=profile, api_key=self._resolve_secret(profile))
                )
            elif profile.http_adapter_config is not None:
                voice_providers.append(
                    GenericHttpVoiceProvider(
                        profile=profile,
                        api_key=self._resolve_secret(profile),
                    )
                )
            else:
                warnings.append(self._inert_warning(profile))

            return

        if profile.category == ProviderCategory.MUSIC:
            coded_music = _CODED_MUSIC.get(self._normalized_name(profile))

            if coded_music is not None:
                music_providers.append(
                    coded_music(profile=profile, api_key=self._resolve_secret(profile))
                )
            elif profile.http_adapter_config is not None:
                music_providers.append(
                    GenericHttpMusicProvider(
                        profile=profile,
                        api_key=self._resolve_secret(profile),
                    )
                )
            else:
                warnings.append(self._inert_warning(profile))

            return

        if profile.category == ProviderCategory.SOUND_EFFECTS:
            coded_sound_effect = _CODED_SOUND_EFFECTS.get(
                self._normalized_name(profile)
            )

            if coded_sound_effect is not None:
                sound_effect_providers.append(
                    coded_sound_effect(
                        profile=profile, api_key=self._resolve_secret(profile)
                    )
                )
            elif profile.http_adapter_config is not None:
                sound_effect_providers.append(
                    GenericHttpSoundEffectProvider(
                        profile=profile,
                        api_key=self._resolve_secret(profile),
                    )
                )
            else:
                warnings.append(self._inert_warning(profile))

            return

        if profile.category in (
            ProviderCategory.STOCK_VIDEO,
            ProviderCategory.STOCK_IMAGE,
        ):
            coded_stock = _CODED_STOCK.get(self._normalized_name(profile))
            target = (
                stock_video_providers
                if profile.category == ProviderCategory.STOCK_VIDEO
                else stock_image_providers
            )

            if coded_stock is not None:
                target.append(
                    coded_stock(profile=profile, api_key=self._resolve_secret(profile))
                )
            elif profile.http_adapter_config is not None:
                target.append(
                    GenericHttpStockProvider(
                        profile=profile,
                        api_key=self._resolve_secret(profile),
                    )
                )
            else:
                warnings.append(self._inert_warning(profile))

            return

        # LLM/VIDEO/IMAGE/UPLOAD: out of scope for this factory.

    def _resolve_secret(self, profile: ProviderProfile) -> str:
        assert profile.secret_reference is not None  # profile.usable guarantees this

        return self._secret_manager.resolve_secret(profile.secret_reference)

    @staticmethod
    def _normalized_name(profile: ProviderProfile) -> str:
        return profile.provider_name.strip().lower()

    @staticmethod
    def _inert_warning(profile: ProviderProfile) -> str:
        return (
            f"Provider profile '{profile.profile_id}' "
            f"({profile.category.value}/{profile.provider_name}) has no "
            "coded adapter and no HTTP adapter configuration; it will not "
            "be used."
        )
