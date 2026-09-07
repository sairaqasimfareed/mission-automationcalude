from __future__ import annotations

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.services.registry.provider_registry import ProviderRegistry


class NoEligibleGoogleFlowAccountError(RuntimeError):
    """Raised when no Google Flow account is currently eligible."""


class GoogleFlowAccountRouterService:
    """
    Google Flow External UI Automation, GF-3: routes one generation
    attempt to the best eligible Google Flow account.

    Deliberately thin - `ProviderRegistry.list_by_category(...,
    usable_only=True)` already does the actual REUSE-confirmed work
    this phase's own "enabled, authenticated, healthy, cooldown,
    priority" ordering asks for (`ProviderProfile.usable` already
    folds in enabled/credential-present/cooldown/health; `list_by_
    category` already returns them priority-then-name-then-id
    ordered). The one thing that registry-level view genuinely cannot
    know is "in-flight work" - how many attempts a given account
    currently has running - since that lives on `VideoJob.
    flow_generation_attempts`, not on `ProviderProfile` itself. This
    service's only real job is layering that one filter on top,
    exactly the seam GF-3's spec draws between "provider registry"
    and "routing."

    "Never fail over during an uncertain submission" is already
    structurally guaranteed one level up, in
    GoogleFlowGenerationLedgerService.create_attempt(): a scene with
    any non-terminal attempt (SUBMISSION_UNCERTAIN included) refuses a
    new attempt outright, on any account - this router is never even
    consulted for that scene until the existing attempt resolves, so
    it cannot accidentally pick a different account mid-uncertainty.
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def select_account(
        self,
        *,
        in_flight_counts: dict[str, int] | None = None,
        max_in_flight_per_account: int = 1,
    ) -> ProviderProfile:
        """
        Return the best eligible Google Flow account, priority order,
        excluding any account already at its in-flight ceiling.

        in_flight_counts is supplied by the caller (a profile_id ->
        current non-terminal-attempt-count mapping) rather than
        computed here, keeping this service decoupled from any
        specific job-store shape - a Flow account can in principle be
        shared across more than one project's jobs, and this service
        has no business assuming how a caller aggregates that.
        """

        if max_in_flight_per_account < 1:
            raise ValueError("max_in_flight_per_account must be at least 1.")

        counts = in_flight_counts or {}

        candidates = self.registry.list_by_category(
            ProviderCategory.EXTERNAL_UI_VIDEO,
            usable_only=True,
        )

        for candidate in candidates:
            if counts.get(candidate.profile_id, 0) < max_in_flight_per_account:
                return candidate

        if not candidates:
            raise NoEligibleGoogleFlowAccountError(
                "No usable Google Flow account is configured."
            )

        raise NoEligibleGoogleFlowAccountError(
            "Every usable Google Flow account is already at its "
            "in-flight attempt limit."
        )
