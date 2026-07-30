from src.config.settings import settings
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.factory.provider_factory import (
    ProviderFactory,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)
from src.shared.llm.dry_run_provider import (
    DryRunProviderAdapter,
)
from src.shared.llm.gemini_provider import (
    GeminiProviderAdapter,
)
from src.shared.llm.openai_provider import (
    OpenAIProviderAdapter,
)


original_dry_run_setting = (
    settings.MISSION_AUTOMATION_DRY_RUN
)

secret_store = InMemorySecretStore()
secret_manager = ProviderSecretManager(
    secret_store
)

openai_secret = secret_manager.create_secret(
    profile_id="openai-main",
    secret_value="openai-secret-key-123456",
)

gemini_secret = secret_manager.create_secret(
    profile_id="gemini-main",
    secret_value="gemini-secret-key-123456",
)

registry = ProviderRegistry(
    profiles=[
        ProviderProfile(
            profile_id="openai-main",
            display_name="OpenAI Main",
            provider_name="OpenAI",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_reference=(
                openai_secret.secret_reference
            ),
            default_model="openai-test-model",
            health_status=(
                ProviderHealthStatus.HEALTHY
            ),
            capabilities=[
                "text_generation",
                "structured_json",
            ],
        ),
        ProviderProfile(
            profile_id="gemini-main",
            display_name="Gemini Main",
            provider_name="Google Gemini",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_reference=(
                gemini_secret.secret_reference
            ),
            default_model="gemini-test-model",
            health_status=(
                ProviderHealthStatus.HEALTHY
            ),
            capabilities=[
                "text_generation",
                "structured_json",
            ],
        ),
    ]
)

factory = ProviderFactory(
    registry=registry,
    secret_manager=secret_manager,
)


settings.MISSION_AUTOMATION_DRY_RUN = False

openai_adapter = factory.create_llm_adapter(
    "openai-main"
)

gemini_adapter = factory.create_llm_adapter(
    "gemini-main"
)

print(
    "OpenAI adapter:",
    type(openai_adapter).__name__,
)

print(
    "Gemini adapter:",
    type(gemini_adapter).__name__,
)

assert isinstance(
    openai_adapter,
    OpenAIProviderAdapter,
)

assert isinstance(
    gemini_adapter,
    GeminiProviderAdapter,
)

assert factory.resolve_default_model(
    "openai-main"
) == "openai-test-model"

assert factory.resolve_default_model(
    "gemini-main"
) == "gemini-test-model"


settings.MISSION_AUTOMATION_DRY_RUN = True

dry_run_adapter = factory.create_llm_adapter(
    "openai-main"
)

assert isinstance(
    dry_run_adapter,
    DryRunProviderAdapter,
)

print(
    "Dry-run adapter selected successfully."
)


unsupported_secret = secret_manager.create_secret(
    profile_id="unsupported-main",
    secret_value="unsupported-secret-123456",
)

unsupported_profile = ProviderProfile(
    profile_id="unsupported-main",
    display_name="Unsupported LLM",
    provider_name="Unknown LLM",
    category=ProviderCategory.LLM,
    enabled=True,
    secret_reference=(
        unsupported_secret.secret_reference
    ),
    default_model="unknown-model",
    health_status=ProviderHealthStatus.HEALTHY,
)

registry.register(
    unsupported_profile
)

settings.MISSION_AUTOMATION_DRY_RUN = False

try:
    factory.create_llm_adapter(
        "unsupported-main"
    )
except ValueError:
    print(
        "Unsupported LLM provider successfully blocked."
    )
else:
    raise AssertionError(
        "Unsupported LLM provider should fail."
    )


settings.MISSION_AUTOMATION_DRY_RUN = (
    original_dry_run_setting
)

print(
    "LLM Secret Factory Integration tests "
    "completed successfully."
)