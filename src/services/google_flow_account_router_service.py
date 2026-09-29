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
        preferred_profile_id: str | None = None,
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

        preferred_profile_id (per-scene manual account picker,
        Scene.preferred_profile_id): when given, looks that profile up
        directly and validates it exactly as the auto path does
        (usable, in-flight limit) - raising a clear, specific error
        naming why if it fails either check, rather than silently
        falling back to a different account (that would defeat the
        point of an explicit operator choice).
        """

        if max_in_flight_per_account < 1:
            raise ValueError("max_in_flight_per_account must be at least 1.")

        counts = in_flight_counts or {}

        if preferred_profile_id is not None:
            return self._select_preferred_account(
                preferred_profile_id,
                counts=counts,
                max_in_flight_per_account=max_in_flight_per_account,
            )

        # Real-world finding, 2026-09-29 (Muse provider architecture
        # investigation): ProviderCategory.EXTERNAL_UI_VIDEO covers
        # ANY browser-driven video provider, not Google Flow
        # exclusively - a Muse account profile registers under this
        # identical category (there is no separate category per
        # provider, by design - see ProviderCategory's own docstring).
        # Without this filter, a registered Muse profile would be
        # returned here as a valid "Flow" candidate the moment one
        # exists, since nothing previously distinguished them.
        candidates = [
            candidate
            for candidate in self.registry.list_by_category(
                ProviderCategory.EXTERNAL_UI_VIDEO,
                usable_only=True,
            )
            if candidate.provider_name == "Google Flow"
        ]

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

    def _select_preferred_account(
        self,
        preferred_profile_id: str,
        *,
        counts: dict[str, int],
        max_in_flight_per_account: int,
    ) -> ProviderProfile:
        try:
            profile = self.registry.get(preferred_profile_id)
        except KeyError:
            raise NoEligibleGoogleFlowAccountError(
                f"The preferred Google Flow account '{preferred_profile_id}' "
                "is not registered."
            ) from None

        if profile.provider_name != "Google Flow":
            raise NoEligibleGoogleFlowAccountError(
                f"'{preferred_profile_id}' is not a Google Flow account "
                f"(it belongs to {profile.provider_name!r})."
            )

        if not profile.usable:
            raise NoEligibleGoogleFlowAccountError(
                f"The preferred Google Flow account '{preferred_profile_id}' "
                "is not currently usable (disabled, uncredentialed, "
                "unhealthy, or in cooldown)."
            )

        if counts.get(profile.profile_id, 0) >= max_in_flight_per_account:
            raise NoEligibleGoogleFlowAccountError(
                f"The preferred Google Flow account '{preferred_profile_id}' "
                "is already at its in-flight attempt limit."
            )

        return profile
