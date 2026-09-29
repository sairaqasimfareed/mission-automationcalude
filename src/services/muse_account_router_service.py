from __future__ import annotations

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.services.registry.provider_registry import ProviderRegistry


class NoEligibleMuseAccountError(RuntimeError):
    """Raised when no Muse account is currently eligible."""


class MuseAccountRouterService:
    """
    Routes one generation attempt to the best eligible Muse account -
    mirrors GoogleFlowAccountRouterService exactly, filtered to
    provider_name == "Muse" rather than "Google Flow" since both share
    ProviderCategory.EXTERNAL_UI_VIDEO (there is no separate category
    per browser-driven video provider, by design).

    "Never fail over during an uncertain submission" is already
    structurally guaranteed one level up, in
    MuseGenerationLedgerService.create_attempt() - same reasoning as
    Google Flow's own router.
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
        Return the best eligible Muse account, priority order,
        excluding any account already at its in-flight ceiling.

        preferred_profile_id: same manual-override contract as
        GoogleFlowAccountRouterService's own equivalent parameter.
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

        candidates = [
            candidate
            for candidate in self.registry.list_by_category(
                ProviderCategory.EXTERNAL_UI_VIDEO,
                usable_only=True,
            )
            if candidate.provider_name == "Muse"
        ]

        for candidate in candidates:
            if counts.get(candidate.profile_id, 0) < max_in_flight_per_account:
                return candidate

        if not candidates:
            raise NoEligibleMuseAccountError("No usable Muse account is configured.")

        raise NoEligibleMuseAccountError(
            "Every usable Muse account is already at its in-flight attempt limit."
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
            raise NoEligibleMuseAccountError(
                f"The preferred Muse account '{preferred_profile_id}' is "
                "not registered."
            ) from None

        if profile.provider_name != "Muse":
            raise NoEligibleMuseAccountError(
                f"'{preferred_profile_id}' is not a Muse account (it "
                f"belongs to {profile.provider_name!r})."
            )

        if not profile.usable:
            raise NoEligibleMuseAccountError(
                f"The preferred Muse account '{preferred_profile_id}' is "
                "not currently usable (disabled, uncredentialed, "
                "unhealthy, or in cooldown)."
            )

        if counts.get(profile.profile_id, 0) >= max_in_flight_per_account:
            raise NoEligibleMuseAccountError(
                f"The preferred Muse account '{preferred_profile_id}' is "
                "already at its in-flight attempt limit."
            )

        return profile
