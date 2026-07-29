from src.models.provider_preferences import (
    ProviderPreference,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.budget.provider_budget_service import (
    ProviderBudgetService,
)
from src.services.factory.provider_factory import (
    LLMProvider,
    ProviderFactory,
)
from src.services.manager.provider_manager import (
    ProviderManager,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.selection.provider_selection_service import (
    ProviderSelectionService,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


store = InMemorySecretStore()

secret_manager = ProviderSecretManager(store)

secret = secret_manager.create_secret(
    profile_id="openai-main",
    secret_value="sk-test-123456789",
)


registry = ProviderRegistry(
    profiles=[
        ProviderProfile(
            profile_id="openai-main",
            display_name="OpenAI",
            provider_name="OpenAI",
            category=ProviderCategory.LLM,
            enabled=True,
            priority=1,
            secret_reference=secret.secret_reference,
            health_status=ProviderHealthStatus.HEALTHY,
            capabilities=[
                "text_generation",
                "structured_json",
            ],
            daily_budget_usd=20.0,
            monthly_budget_usd=100.0,
            per_request_budget_usd=5.0,
        )
    ]
)

selection_service = ProviderSelectionService(
    registry
)

budget_service = ProviderBudgetService(
    registry
)

factory = ProviderFactory(
    registry=registry,
    secret_manager=secret_manager,
)

manager = ProviderManager(
    registry=registry,
    selection_service=selection_service,
    budget_service=budget_service,
    factory=factory,
)


provider = manager.get_provider(
    category=ProviderCategory.LLM,
    estimated_cost_usd=2.0,
    required_capability="text_generation",
)

print(type(provider).__name__)

assert isinstance(
    provider,
    LLMProvider,
)

assert (
    provider.instance.profile_id
    == "openai-main"
)

assert (
    provider.api_key
    == "sk-test-123456789"
)


preferred = manager.get_provider(
    category=ProviderCategory.LLM,
    estimated_cost_usd=1.0,
    preference=ProviderPreference(
        preferred_profile_id="openai-main",
    ),
)

assert isinstance(
    preferred,
    LLMProvider,
)


try:
    manager.get_provider(
        category=ProviderCategory.LLM,
        estimated_cost_usd=100.0,
    )
except ValueError:
    print(
        "Budget protection works."
    )
else:
    raise AssertionError(
        "Budget validation should fail."
    )


print(
    "Provider Manager tests completed successfully."
)