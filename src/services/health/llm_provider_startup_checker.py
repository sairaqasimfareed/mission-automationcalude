from __future__ import annotations

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.services.factory.provider_factory import ProviderFactory


class LLMProviderStartupChecker:
    """
    Lightweight startup readiness check for LLM provider profiles.

    Verifies that a profile's secret resolves and that its adapter can
    be constructed, without performing any live network request. Real
    upstream connectivity is intentionally out of scope for
    application startup: a slow or unreachable provider should not
    block the composition root from finishing, and adapter
    construction alone (secret resolution, provider-name recognition)
    already catches the common misconfiguration cases.
    """

    def __init__(self, provider_factory: ProviderFactory) -> None:
        self._provider_factory = provider_factory

    def check(
        self,
        profile: ProviderProfile,
    ) -> tuple[bool, str]:
        if profile.category != ProviderCategory.LLM:
            return (
                True,
                "Startup validation only covers LLM provider profiles.",
            )

        try:
            self._provider_factory.create_llm_adapter(profile.profile_id)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

        return True, "Provider adapter constructed successfully."
