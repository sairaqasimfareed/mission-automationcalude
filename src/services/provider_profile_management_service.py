from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from src.models.provider_profile import ProviderHealthStatus, ProviderProfile
from src.models.provider_profile_management import (
    ProviderProfileSummary,
    ProviderProfileUpsertCommand,
)
from src.services.health.provider_health_service import (
    ProviderHealthChecker,
    ProviderHealthResult,
    ProviderHealthService,
)
from src.services.registry.provider_profile_repository import (
    ProviderProfileRepository,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.secrets.provider_secret_manager import ProviderSecretManager


class ProviderSecretResolutionChecker:
    """
    Generic provider health check: verifies a profile's secret resolves.

    Unlike LLMProviderStartupChecker, this applies to every provider
    category (voice, image, stock footage, and so on), since Provider
    Manager needs a check that works before any category-specific
    adapter exists.
    """

    def __init__(
        self,
        secret_manager: ProviderSecretManager,
    ) -> None:
        self._secret_manager = secret_manager

    def check(
        self,
        profile: ProviderProfile,
    ) -> tuple[bool, str]:
        if not profile.secret_reference:
            return False, "Provider profile has no secret configured."

        try:
            self._secret_manager.resolve_secret(profile.secret_reference)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

        return True, "Secret resolves successfully."


class ProviderProfileManagementService:
    """
    Desktop-facing CRUD for provider profiles.

    Keeps ProviderRegistry (the in-memory registry selection/execution
    reads at runtime) and ProviderProfileRepository (durable JSON
    storage) in sync: every mutation writes through to the repository
    immediately, and load() seeds the registry from the repository at
    startup. This gives the desktop app provider profiles that survive
    a restart without requiring every profile to come from an
    environment variable, unlike RuntimeConfigurationLoader's current
    LLM-only, env-driven bootstrap.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        repository: ProviderProfileRepository,
        secret_manager: ProviderSecretManager,
        health_service: ProviderHealthService | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._secret_manager = secret_manager
        self._health_service = health_service or ProviderHealthService(
            registry=registry,
        )
        self._health_checker: ProviderHealthChecker = ProviderSecretResolutionChecker(
            secret_manager,
        )

    def load(self) -> list[ProviderProfileSummary]:
        """Seed the registry from durable storage and return all profiles."""

        for profile in self._repository.load_all():
            self._registry.register(profile, replace=True)

        return self.list_profiles()

    def list_profiles(self) -> list[ProviderProfileSummary]:
        return [self._to_summary(profile) for profile in self._registry.list_all()]

    def get_profile(
        self,
        profile_id: str,
    ) -> ProviderProfileSummary:
        return self._to_summary(self._registry.get(profile_id))

    def upsert_profile(
        self,
        command: ProviderProfileUpsertCommand,
    ) -> ProviderProfileSummary:
        """Create a new profile, or update an existing one in place."""

        existing = (
            self._registry.get(command.profile_id)
            if self._registry.contains(command.profile_id)
            else None
        )

        secret_reference = existing.secret_reference if existing else None

        if command.secret_value:
            if secret_reference:
                self._secret_manager.replace_secret(
                    secret_reference=secret_reference,
                    new_secret_value=command.secret_value,
                )
            else:
                secret_reference = self._secret_manager.create_secret(
                    profile_id=command.profile_id,
                    secret_value=command.secret_value,
                ).secret_reference

        profile = ProviderProfile(
            id=existing.id if existing else uuid4(),
            created_at=existing.created_at if existing else datetime.now(UTC),
            profile_id=command.profile_id,
            display_name=command.display_name,
            provider_name=command.provider_name,
            category=command.category,
            enabled=command.enabled,
            priority=command.priority,
            secret_reference=secret_reference,
            base_url=command.base_url,
            organization_id=command.organization_id,
            project_id=command.project_id,
            region=command.region,
            default_model=command.default_model,
            daily_budget_usd=command.daily_budget_usd,
            daily_spent_usd=existing.daily_spent_usd if existing else 0.0,
            monthly_budget_usd=command.monthly_budget_usd,
            monthly_spent_usd=existing.monthly_spent_usd if existing else 0.0,
            per_request_budget_usd=command.per_request_budget_usd,
            timeout_seconds=command.timeout_seconds,
            maximum_retries=command.maximum_retries,
            health_status=(
                existing.health_status if existing else ProviderHealthStatus.UNKNOWN
            ),
            capabilities=command.capabilities,
            metadata=command.metadata,
            http_adapter_config=command.http_adapter_config,
        )

        self._registry.register(profile, replace=True)
        self._persist()

        return self._to_summary(profile)

    def delete_profile(
        self,
        profile_id: str,
    ) -> None:
        profile = self._registry.unregister(profile_id)

        if profile.secret_reference and self._secret_manager.secret_exists(
            profile.secret_reference
        ):
            self._secret_manager.delete_secret(profile.secret_reference)

        self._persist()

    def set_enabled(
        self,
        profile_id: str,
        enabled: bool,
    ) -> ProviderProfileSummary:
        profile = self._registry.get(profile_id)

        if enabled and not profile.secret_reference:
            raise ValueError(
                "Cannot enable a provider profile without a secret configured."
            )

        updated = profile.model_copy(update={"enabled": enabled})

        self._registry.register(updated, replace=True)
        self._persist()

        return self._to_summary(updated)

    def check_health(
        self,
        profile_id: str,
    ) -> ProviderHealthResult:
        return self._health_service.check_profile(profile_id, self._health_checker)

    def _persist(self) -> None:
        self._repository.save_all(self._registry.list_all())

    def _to_summary(
        self,
        profile: ProviderProfile,
    ) -> ProviderProfileSummary:
        masked_secret = None

        if profile.secret_reference and self._secret_manager.secret_exists(
            profile.secret_reference
        ):
            masked_secret = self._secret_manager.get_masked_secret(
                profile.secret_reference
            )

        return ProviderProfileSummary(
            profile_id=profile.profile_id,
            display_name=profile.display_name,
            provider_name=profile.provider_name,
            category=profile.category,
            enabled=profile.enabled,
            priority=profile.priority,
            health_status=profile.health_status,
            has_secret=profile.secret_reference is not None,
            masked_secret=masked_secret,
            base_url=profile.base_url,
            organization_id=profile.organization_id,
            project_id=profile.project_id,
            region=profile.region,
            default_model=profile.default_model,
            daily_budget_usd=profile.daily_budget_usd,
            monthly_budget_usd=profile.monthly_budget_usd,
            per_request_budget_usd=profile.per_request_budget_usd,
            timeout_seconds=profile.timeout_seconds,
            maximum_retries=profile.maximum_retries,
            capabilities=profile.capabilities,
            metadata=profile.metadata,
            http_adapter_config=profile.http_adapter_config,
        )
