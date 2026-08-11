from __future__ import annotations

from dataclasses import dataclass

from src.models.provider_profile import ProviderCategory
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
)
from src.services.health.llm_provider_startup_checker import (
    LLMProviderStartupChecker,
)
from src.services.health.provider_health_service import (
    ProviderHealthResult,
    ProviderHealthService,
)


@dataclass(frozen=True, slots=True)
class ProviderStartupValidationResult:
    """Outcome of one startup validation pass over LLM provider profiles."""

    results: list[ProviderHealthResult]

    @property
    def healthy_profile_ids(self) -> list[str]:
        """Return profile IDs that passed startup validation."""

        return [result.profile_id for result in self.results if result.healthy]


class ProviderStartupValidator:
    """
    Run startup readiness checks against enabled LLM provider profiles.

    This is a deliberately separate step from ApplicationInfrastructureFactory
    and ProductionApplicationFactory composition: those factories build
    dependency graphs only and intentionally do not execute
    provider-specific logic. Validation is invoked explicitly by the
    caller (for example, an application entrypoint) once a runtime has
    already been composed.

    At least one enabled LLM provider profile must pass validation, or
    the production application has nothing usable to run content
    generation through.
    """

    def __init__(self, infrastructure: ApplicationInfrastructure) -> None:
        self._registry = infrastructure.provider_registry

        self._health_service = ProviderHealthService(
            registry=self._registry,
        )

        self._checker = LLMProviderStartupChecker(
            infrastructure.provider_factory,
        )

    def validate(self) -> ProviderStartupValidationResult:
        """Check every enabled LLM provider profile and update its status."""

        profiles = self._registry.list_by_category(
            ProviderCategory.LLM,
            enabled_only=True,
        )

        if not profiles:
            raise ValueError(
                "Provider startup validation requires at least one "
                "enabled LLM provider profile."
            )

        results = [
            self._health_service.check_profile(profile.profile_id, self._checker)
            for profile in profiles
        ]

        if not any(result.healthy for result in results):
            raise ValueError("No configured LLM provider passed startup validation.")

        return ProviderStartupValidationResult(results=results)
