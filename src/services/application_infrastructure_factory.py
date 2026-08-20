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
    ) -> ApplicationInfrastructure:
        """
        Build one internally consistent shared dependency graph.

        A single ProviderRegistry instance is shared across the provider
        factory, budget service, and LLM service.

        Provider secrets remain externally supplied runtime state and are
        never synthesized by this factory.
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
