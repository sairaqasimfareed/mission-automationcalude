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
from src.shared.llm.models import (
    LLMProvider as SharedLLMProvider,
)
from src.shared.llm.provider_factory import (
    create_provider_adapter,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
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
    """Base runtime provider wrapper."""

    def __init__(
        self,
        instance: ProviderInstance,
        api_key: str,
    ) -> None:
        self.instance = instance
        self.api_key = api_key


class LLMProvider(BaseProvider):
    """Generic LLM runtime wrapper."""


class VideoProvider(BaseProvider):
    """Generic video runtime wrapper."""


class VoiceProvider(BaseProvider):
    """Generic voice runtime wrapper."""


class ImageProvider(BaseProvider):
    """Generic image runtime wrapper."""


class ProviderFactory:
    """Creates configured runtime providers and LLM adapters."""

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
        """
        Create a generic runtime provider wrapper.

        This method remains available for video, voice,
        image and backward-compatible LLM workflows.
        """

        profile = self.registry.get(profile_id)
        secret = self._resolve_profile_secret(profile)
        instance = self._build_instance(profile)

        if profile.category == ProviderCategory.LLM:
            return LLMProvider(
                instance,
                secret,
            )

        if profile.category == ProviderCategory.VIDEO:
            return VideoProvider(
                instance,
                secret,
            )

        if profile.category == ProviderCategory.VOICE:
            return VoiceProvider(
                instance,
                secret,
            )

        if profile.category == ProviderCategory.IMAGE:
            return ImageProvider(
                instance,
                secret,
            )

        raise ValueError(
            "Unsupported provider category: "
            f"{profile.category.value}"
        )

    def create_llm_adapter(
        self,
        profile_id: str,
    ) -> LLMProviderAdapter:
        """
        Create a production LLM adapter from one profile.

        The API key is resolved internally through the
        ProviderSecretManager and is never returned.
        """

        profile = self.registry.get(profile_id)

        if profile.category != ProviderCategory.LLM:
            raise ValueError(
                "The selected provider profile is not "
                "an LLM provider."
            )

        secret = self._resolve_profile_secret(profile)

        llm_provider = self._resolve_llm_provider(
            profile.provider_name
        )

        return create_provider_adapter(
            provider=llm_provider,
            api_key=secret,
        )

    def resolve_default_model(
        self,
        profile_id: str,
    ) -> str:
        """Return the configured default model for one profile."""

        profile = self.registry.get(profile_id)

        if profile.category != ProviderCategory.LLM:
            raise ValueError(
                "Default LLM model can only be resolved "
                "for an LLM provider profile."
            )

        if (
            profile.default_model is None
            or not profile.default_model.strip()
        ):
            raise ValueError(
                "Provider profile has no default model."
            )

        return profile.default_model.strip()

    def _resolve_profile_secret(
        self,
        profile: ProviderProfile,
    ) -> str:
        """Resolve one profile secret safely."""

        if not profile.secret_reference:
            raise ValueError(
                "Provider profile has no secret reference."
            )

        return self.secret_manager.resolve_secret(
            profile.secret_reference
        )

    @staticmethod
    def _resolve_llm_provider(
        provider_name: str,
    ) -> SharedLLMProvider:
        """Convert a profile provider name into an LLM enum."""

        normalized_name = (
            provider_name
            .strip()
            .lower()
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
        )

        aliases: dict[str, SharedLLMProvider] = {
    "openai": SharedLLMProvider.OPENAI,
    "chatgpt": SharedLLMProvider.OPENAI,

    "gemini": SharedLLMProvider.GEMINI,
    "google": SharedLLMProvider.GEMINI,
    "googleai": SharedLLMProvider.GEMINI,
    "googleaistudio": SharedLLMProvider.GEMINI,
    "googlegemini": SharedLLMProvider.GEMINI,
    "geminigoogle": SharedLLMProvider.GEMINI,

    "anthropic": SharedLLMProvider.ANTHROPIC,
    "claude": SharedLLMProvider.ANTHROPIC,
}
        

        if normalized_name not in aliases:
            raise ValueError(
                "Unsupported LLM provider name: "
                f"{provider_name}"
            )

        return aliases[normalized_name]

    @staticmethod
    def _build_instance(
        profile: ProviderProfile,
    ) -> ProviderInstance:
        """Build a validated runtime provider instance."""

        if not profile.secret_reference:
            raise ValueError(
                "Provider profile has no secret reference."
            )

        return ProviderInstance(
            profile_id=profile.profile_id,
            provider_name=profile.provider_name,
            category=profile.category,
            secret_reference=profile.secret_reference,
            default_model=profile.default_model,
        )