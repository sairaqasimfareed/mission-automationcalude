from __future__ import annotations

from src.providers.base_provider import BaseProvider


class ProviderRegistry:
    """Central registry for external service providers."""

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}

    def register(self, provider: BaseProvider) -> None:
        """Register or replace a provider by name."""

        self._providers[provider.provider_name] = provider

    def get(self, provider_name: str) -> BaseProvider:
        """Return a registered provider."""

        try:
            return self._providers[provider_name]
        except KeyError as error:
            raise KeyError(f"Provider is not registered: {provider_name}") from error

    def is_registered(self, provider_name: str) -> bool:
        """Return whether a provider is registered."""

        return provider_name in self._providers

    def healthy_providers(self) -> list[str]:
        """Return the names of providers passing their health check."""

        return [
            name
            for name, provider in self._providers.items()
            if provider.health_check()
        ]
