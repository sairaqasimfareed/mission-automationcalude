from __future__ import annotations

from abc import ABC

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.provider_profile import (
    ProviderCategory,
    ProviderProfile,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.secrets.provider_secret_manager import (
    ProviderSecretManager,
)


class ProviderInstance(MissionBaseModel):
    """Runtime provider instance."""

    profile_id: str
    provider_name: str
    category: ProviderCategory

    secret_reference: str

    default_model: str | None = None

    configuration: dict[str, str] = Field(
        default_factory=dict,
    )


class BaseProvider(ABC):
    """Base provider."""

    def __init__(
        self,
        instance: ProviderInstance,
        api_key: str,
    ) -> None:
        self.instance = instance
        self.api_key = api_key


class LLMProvider(BaseProvider):
    pass


class VideoProvider(BaseProvider):
    pass


class VoiceProvider(BaseProvider):
    pass


class ImageProvider(BaseProvider):
    pass


class ProviderFactory:
    """Creates configured provider instances."""

    def __init__(
        self,
        registry: ProviderRegistry,
        secret_manager: ProviderSecretManager,
    ) -> None:
        self.registry = registry
        self.secret_manager = secret_manager

    def create(
        self,
        profile_id: str,
    ) -> BaseProvider:
        """Create one configured runtime provider."""

        profile = self.registry.get(profile_id)

        if not profile.secret_reference:
            raise ValueError("Provider profile has no secret reference.")

        secret = self.secret_manager.resolve_secret(profile.secret_reference)

        instance = self._build_instance(profile)

        if profile.category == ProviderCategory.LLM:
            return LLMProvider(instance, secret)

        if profile.category == ProviderCategory.VIDEO:
            return VideoProvider(instance, secret)

        if profile.category == ProviderCategory.VOICE:
            return VoiceProvider(instance, secret)

        if profile.category == ProviderCategory.IMAGE:
            return ImageProvider(instance, secret)

        raise ValueError("Unsupported provider category: " f"{profile.category}")

    @staticmethod
    def _build_instance(
        profile: ProviderProfile,
    ) -> ProviderInstance:
        """Build a validated runtime provider instance."""

        if not profile.secret_reference:
            raise ValueError("Provider profile has no secret reference.")

        return ProviderInstance(
            profile_id=profile.profile_id,
            provider_name=profile.provider_name,
            category=profile.category,
            secret_reference=profile.secret_reference,
            default_model=profile.default_model,
        )
