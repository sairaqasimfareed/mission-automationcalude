from __future__ import annotations

from dataclasses import dataclass

from src.models.provider_profile import ProviderProfile
from src.services.budget.provider_budget_service import (
    ProviderBudgetService,
)
from src.services.factory.provider_factory import (
    ProviderFactory,
)
from src.services.llm.llm_service import (
    LLMService,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.secrets.provider_secret_manager import (
    ProviderSecretManager,
    SecretStore,
)
from src.shared.llm.gateway import (
    LLMGateway,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ApplicationInfrastructure:
    """
    Shared application infrastructure constructed for one runtime.

    These services are application-lifetime dependencies.

    Per-job values such as resolved voice blueprints, genre identifiers,
    timeline overrides, and other execution-specific configuration do
    not belong in this container.
    """

    provider_registry: ProviderRegistry
    provider_secret_manager: ProviderSecretManager
    provider_factory: ProviderFactory
    provider_budget_service: ProviderBudgetService
    llm_gateway: LLMGateway
    llm_service: LLMService


class ApplicationInfrastructureFactory:
    """
    Compose shared provider and LLM infrastructure.

    This factory performs dependency construction only.

    It deliberately does not:

    - invent provider profiles;
    - create provider secrets;
    - select providers for individual jobs;
    - construct per-job render stages;
    - resolve voice blueprints;
    - execute LLM requests.

    Those responsibilities remain with their existing services.
    """

    def __init__(
        self,
        *,
        secret_store: SecretStore,
    ) -> None:
        self._secret_store = secret_store

    @property
    def secret_store(
        self,
    ) -> SecretStore:
        """Return the configured runtime secret store."""

        return self._secret_store

    def build(
        self,
        *,
        provider_profiles: list[ProviderProfile] | None = None,
        llm_gateway: LLMGateway | None = None,
        dry_run: bool | None = None,
    ) -> ApplicationInfrastructure:
        """
        Build one internally consistent shared dependency graph.

        A single ProviderRegistry instance is shared across the provider
        factory, budget service, and LLM service.

        Provider secrets remain externally supplied runtime state and are
        never synthesized by this factory.

        dry_run defaults to None (forwarded straight through to
        ProviderFactory, itself defaulting to the same dynamic global-
        settings fallback create_provider_adapter() has always had -
        this method's exact prior behavior for every caller that
        doesn't pass it). Real bug found and fixed 2026-09-24:
        ProductionApplicationFactory.build() now passes its own real,
        explicitly-configured AdvancedSettings.dry_run here instead of
        omitting it - omitting it used to leave LLM adapter selection
        silently trusting a global settings singleton (loaded once
        from the real .env file) instead of whatever dry-run state
        THIS runtime was actually built with, producing a real network
        call - and a real, confusing 401 - using a dry-run placeholder
        secret as if it were a real key.
        """

        registry = ProviderRegistry(
            profiles=provider_profiles,
        )

        secret_manager = ProviderSecretManager(
            secret_store=self._secret_store,
        )

        provider_factory = ProviderFactory(
            registry=registry,
            secret_manager=secret_manager,
            dry_run=dry_run,
        )

        budget_service = ProviderBudgetService(
            registry=registry,
        )

        gateway = llm_gateway if llm_gateway is not None else LLMGateway()

        llm_service = LLMService(
            registry=registry,
            provider_factory=provider_factory,
            budget_service=budget_service,
            gateway=gateway,
        )

        return ApplicationInfrastructure(
            provider_registry=registry,
            provider_secret_manager=secret_manager,
            provider_factory=provider_factory,
            provider_budget_service=budget_service,
            llm_gateway=gateway,
            llm_service=llm_service,
        )
