from __future__ import annotations

from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
    ApplicationInfrastructureFactory,
)
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
    InMemorySecretStore,
    ProviderSecretManager,
)
from src.shared.llm.gateway import (
    LLMGateway,
)


def test_factory_preserves_secret_store() -> None:
    secret_store = InMemorySecretStore()

    factory = ApplicationInfrastructureFactory(
        secret_store=secret_store,
    )

    assert factory.secret_store is secret_store


def test_build_returns_complete_infrastructure() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert isinstance(
        infrastructure,
        ApplicationInfrastructure,
    )

    assert isinstance(
        infrastructure.provider_registry,
        ProviderRegistry,
    )

    assert isinstance(
        infrastructure.provider_secret_manager,
        ProviderSecretManager,
    )

    assert isinstance(
        infrastructure.provider_factory,
        ProviderFactory,
    )

    assert isinstance(
        infrastructure.provider_budget_service,
        ProviderBudgetService,
    )

    assert isinstance(
        infrastructure.llm_gateway,
        LLMGateway,
    )

    assert isinstance(
        infrastructure.llm_service,
        LLMService,
    )


def test_build_uses_injected_secret_store() -> None:
    secret_store = InMemorySecretStore()

    factory = ApplicationInfrastructureFactory(
        secret_store=secret_store,
    )

    infrastructure = factory.build()

    assert infrastructure.provider_secret_manager.secret_store is secret_store


def test_build_shares_registry_with_provider_factory() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert infrastructure.provider_factory.registry is infrastructure.provider_registry


def test_build_shares_registry_with_budget_service() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert (
        infrastructure.provider_budget_service.registry
        is infrastructure.provider_registry
    )


def test_build_shares_registry_with_llm_service() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert infrastructure.llm_service.registry is infrastructure.provider_registry


def test_build_shares_provider_factory_with_llm_service() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert (
        infrastructure.llm_service.provider_factory is infrastructure.provider_factory
    )


def test_build_shares_budget_service_with_llm_service() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert (
        infrastructure.llm_service.budget_service
        is infrastructure.provider_budget_service
    )


def test_build_shares_gateway_with_llm_service() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert infrastructure.llm_service.gateway is infrastructure.llm_gateway


def test_build_preserves_injected_gateway() -> None:
    gateway = LLMGateway()

    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build(
        llm_gateway=gateway,
    )

    assert infrastructure.llm_gateway is gateway
    assert infrastructure.llm_service.gateway is gateway


def test_build_creates_fresh_runtime_graph() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    first = factory.build()
    second = factory.build()

    assert first is not second

    assert first.provider_registry is not second.provider_registry

    assert first.provider_secret_manager is not second.provider_secret_manager

    assert first.provider_factory is not second.provider_factory

    assert first.provider_budget_service is not second.provider_budget_service

    assert first.llm_gateway is not second.llm_gateway

    assert first.llm_service is not second.llm_service


def test_build_reuses_secret_store_across_runtime_graphs() -> None:
    secret_store = InMemorySecretStore()

    factory = ApplicationInfrastructureFactory(
        secret_store=secret_store,
    )

    first = factory.build()
    second = factory.build()

    assert first.provider_secret_manager.secret_store is secret_store

    assert second.provider_secret_manager.secret_store is secret_store


def test_infrastructure_is_frozen() -> None:
    factory = ApplicationInfrastructureFactory(
        secret_store=InMemorySecretStore(),
    )

    infrastructure = factory.build()

    assert infrastructure.provider_registry is infrastructure.llm_service.registry
