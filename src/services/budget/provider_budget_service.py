from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.provider_profile import ProviderProfile
from src.services.registry.provider_registry import (
    ProviderRegistry,
)


class ProviderBudgetCheckResult(MissionBaseModel):
    """Result of checking a provider request against its budgets."""

    profile_id: str
    requested_cost_usd: float = Field(ge=0.0)

    allowed: bool
    reason: str

    remaining_daily_budget_usd: float | None = None
    remaining_monthly_budget_usd: float | None = None

    per_request_limit_usd: float | None = None


class ProviderBudgetService:
    """Checks, reserves, releases, and records provider spending."""

    def __init__(
        self,
        registry: ProviderRegistry,
    ) -> None:
        self.registry = registry

    def check_request(
        self,
        profile_id: str,
        estimated_cost_usd: float,
    ) -> ProviderBudgetCheckResult:
        """Check whether a provider can afford one request."""

        if estimated_cost_usd < 0:
            raise ValueError("Estimated request cost cannot be negative.")

        profile = self.registry.get(profile_id)

        remaining_daily = profile.remaining_daily_budget_usd
        remaining_monthly = profile.remaining_monthly_budget_usd

        per_request_limit = (
            profile.per_request_budget_usd
            if profile.per_request_budget_usd > 0
            else None
        )

        if per_request_limit is not None and estimated_cost_usd > per_request_limit:
            return ProviderBudgetCheckResult(
                profile_id=profile.profile_id,
                requested_cost_usd=estimated_cost_usd,
                allowed=False,
                reason=("Estimated cost exceeds the configured " "per-request budget."),
                remaining_daily_budget_usd=remaining_daily,
                remaining_monthly_budget_usd=remaining_monthly,
                per_request_limit_usd=per_request_limit,
            )

        if remaining_daily is not None and estimated_cost_usd > remaining_daily:
            return ProviderBudgetCheckResult(
                profile_id=profile.profile_id,
                requested_cost_usd=estimated_cost_usd,
                allowed=False,
                reason=("Estimated cost exceeds the remaining " "daily budget."),
                remaining_daily_budget_usd=remaining_daily,
                remaining_monthly_budget_usd=remaining_monthly,
                per_request_limit_usd=per_request_limit,
            )

        if remaining_monthly is not None and estimated_cost_usd > remaining_monthly:
            return ProviderBudgetCheckResult(
                profile_id=profile.profile_id,
                requested_cost_usd=estimated_cost_usd,
                allowed=False,
                reason=("Estimated cost exceeds the remaining " "monthly budget."),
                remaining_daily_budget_usd=remaining_daily,
                remaining_monthly_budget_usd=remaining_monthly,
                per_request_limit_usd=per_request_limit,
            )

        return ProviderBudgetCheckResult(
            profile_id=profile.profile_id,
            requested_cost_usd=estimated_cost_usd,
            allowed=True,
            reason="Provider budget is available.",
            remaining_daily_budget_usd=remaining_daily,
            remaining_monthly_budget_usd=remaining_monthly,
            per_request_limit_usd=per_request_limit,
        )

    def reserve(
        self,
        profile_id: str,
        estimated_cost_usd: float,
    ) -> ProviderProfile:
        """Reserve estimated cost against provider budgets."""

        result = self.check_request(
            profile_id=profile_id,
            estimated_cost_usd=estimated_cost_usd,
        )

        if not result.allowed:
            raise ValueError(result.reason)

        profile = self.registry.get(profile_id)

        updated_profile = profile.model_copy(
            update={
                "daily_spent_usd": self._normalize_amount(
                    profile.daily_spent_usd + estimated_cost_usd
                ),
                "monthly_spent_usd": self._normalize_amount(
                    profile.monthly_spent_usd + estimated_cost_usd
                ),
            }
        )

        self.registry.register(
            updated_profile,
            replace=True,
        )

        return updated_profile

    def release(
        self,
        profile_id: str,
        reserved_cost_usd: float,
    ) -> ProviderProfile:
        """Release previously reserved provider cost."""

        if reserved_cost_usd < 0:
            raise ValueError("Released cost cannot be negative.")

        profile = self.registry.get(profile_id)

        if reserved_cost_usd > profile.daily_spent_usd:
            raise ValueError("Released cost cannot exceed daily spending.")

        if reserved_cost_usd > profile.monthly_spent_usd:
            raise ValueError("Released cost cannot exceed monthly spending.")

        updated_profile = profile.model_copy(
            update={
                "daily_spent_usd": self._normalize_amount(
                    profile.daily_spent_usd - reserved_cost_usd
                ),
                "monthly_spent_usd": self._normalize_amount(
                    profile.monthly_spent_usd - reserved_cost_usd
                ),
            }
        )

        self.registry.register(
            updated_profile,
            replace=True,
        )

        return updated_profile

    def adjust_reserved_cost(
        self,
        profile_id: str,
        *,
        reserved_cost_usd: float,
        actual_cost_usd: float,
    ) -> ProviderProfile:
        """Replace an estimated reservation with the actual cost."""

        if reserved_cost_usd < 0:
            raise ValueError("Reserved cost cannot be negative.")

        if actual_cost_usd < 0:
            raise ValueError("Actual cost cannot be negative.")

        profile = self.release(
            profile_id=profile_id,
            reserved_cost_usd=reserved_cost_usd,
        )

        if actual_cost_usd == 0:
            return profile

        return self.reserve(
            profile_id=profile_id,
            estimated_cost_usd=actual_cost_usd,
        )

    def remaining_daily_budget(
        self,
        profile_id: str,
    ) -> float | None:
        """Return remaining daily budget or None when unlimited."""

        return self.registry.get(profile_id).remaining_daily_budget_usd

    def remaining_monthly_budget(
        self,
        profile_id: str,
    ) -> float | None:
        """Return remaining monthly budget or None when unlimited."""

        return self.registry.get(profile_id).remaining_monthly_budget_usd

    def is_budget_available(
        self,
        profile_id: str,
        estimated_cost_usd: float,
    ) -> bool:
        """Return whether the requested estimated cost is allowed."""

        return self.check_request(
            profile_id=profile_id,
            estimated_cost_usd=estimated_cost_usd,
        ).allowed

    @staticmethod
    def _normalize_amount(
        amount: float,
    ) -> float:
        """Normalize floating-point currency calculations."""

        return round(amount, 6)
