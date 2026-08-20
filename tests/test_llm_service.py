from __future__ import annotations

from collections.abc import Callable

from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
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
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.models import (
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
    LLMProviderResponse,
)
from src.shared.llm.request import LLMRequest
from src.shared.llm.retry import RetryConfig


class FailingAdapter(LLMProviderAdapter):
    """Provider that always fails."""

    provider = LLMProvider.OPENAI

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        def operation() -> LLMProviderResponse:
            raise RuntimeError("Primary provider failed.")

        return operation


class SuccessfulAdapter(LLMProviderAdapter):
    """Provider that returns a successful response."""

    provider = LLMProvider.GEMINI

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        def operation() -> LLMProviderResponse:
            return LLMProviderResponse(
                content="Fallback provider succeeded.",
                usage=LLMUsage(
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    estimated_cost_usd=0.25,
                ),
                provider_request_id=("gemini-request-001"),
                metadata={
                    "test": True,
                },
            )

        return operation


secret_store = InMemorySecretStore()

secret_manager = ProviderSecretManager(secret_store)

openai_secret = secret_manager.create_secret(
    profile_id="openai-main",
    secret_value="openai-secret-123456",
)

gemini_secret = secret_manager.create_secret(
    profile_id="gemini-backup",
    secret_value="gemini-secret-123456",
)


registry = ProviderRegistry(
    profiles=[
        ProviderProfile(
            profile_id="openai-main",
            display_name="OpenAI Main",
            provider_name="OpenAI",
            category=ProviderCategory.LLM,
            enabled=True,
            priority=1,
            secret_reference=(openai_secret.secret_reference),
            default_model="openai-test-model",
            health_status=(ProviderHealthStatus.HEALTHY),
            capabilities=[
                "text_generation",
            ],
            daily_budget_usd=10.0,
            monthly_budget_usd=100.0,
            per_request_budget_usd=5.0,
        ),
        ProviderProfile(
            profile_id="gemini-backup",
            display_name="Gemini Backup",
            provider_name="Google Gemini",
            category=ProviderCategory.LLM,
            enabled=True,
            priority=2,
            secret_reference=(gemini_secret.secret_reference),
            default_model="gemini-test-model",
            health_status=(ProviderHealthStatus.HEALTHY),
            capabilities=[
                "text_generation",
            ],
            daily_budget_usd=10.0,
            monthly_budget_usd=100.0,
            per_request_budget_usd=5.0,
        ),
    ]
)


provider_factory = ProviderFactory(
    registry=registry,
    secret_manager=secret_manager,
)

budget_service = ProviderBudgetService(registry)

gateway = LLMGateway(
    retry_config=RetryConfig(
        max_attempts=1,
        initial_delay_seconds=0.0,
        max_delay_seconds=0.0,
    )
)


def resolve_test_adapter(
    profile_id: str,
) -> LLMProviderAdapter:
    if profile_id == "openai-main":
        return FailingAdapter()

    if profile_id == "gemini-backup":
        return SuccessfulAdapter()

    raise KeyError(f"Unexpected profile: {profile_id}")


service = LLMService(
    registry=registry,
    provider_factory=provider_factory,
    budget_service=budget_service,
    gateway=gateway,
    adapter_resolver=resolve_test_adapter,
)


request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="request-default-model",
    prompt="Generate a test response.",
    prompt_version="v1",
)


service_result = service.generate(
    request,
    estimated_cost_usd=1.0,
)

print(
    "Selected profile:",
    service_result.selected_profile_id,
)

print(
    "Attempts:",
    service_result.attempted_profile_ids,
)

print(
    "Content:",
    service_result.result.content,
)

assert service_result.is_success is True

assert service_result.selected_profile_id == "gemini-backup"

assert service_result.used_failover is True

assert service_result.attempted_profile_ids == [
    "openai-main",
    "gemini-backup",
]

assert service_result.result.content == "Fallback provider succeeded."

assert service_result.result.provider == LLMProvider.GEMINI

assert service_result.result.provider_request_id == "gemini-request-001"

assert len(service_result.attempts) == 2


openai_profile = registry.get("openai-main")

gemini_profile = registry.get("gemini-backup")

assert openai_profile.health_status == ProviderHealthStatus.DEGRADED

assert gemini_profile.health_status == ProviderHealthStatus.HEALTHY

assert openai_profile.daily_spent_usd == 0.0
assert openai_profile.monthly_spent_usd == 0.0

assert gemini_profile.daily_spent_usd == 0.25
assert gemini_profile.monthly_spent_usd == 0.25


explicit_result = service.generate(
    request,
    estimated_cost_usd=0.0,
    profile_ids=[
        "gemini-backup",
    ],
)

assert explicit_result.is_success is True
assert explicit_result.used_failover is False
assert explicit_result.attempted_profile_ids == [
    "gemini-backup",
]


try:
    service.generate(
        request,
        estimated_cost_usd=-1.0,
    )
except ValueError:
    print("Negative estimated cost successfully blocked.")
else:
    raise AssertionError("Negative estimated cost should fail.")


print("LLM Service tests completed successfully.")
