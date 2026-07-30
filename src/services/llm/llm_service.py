from __future__ import annotations

from collections.abc import Callable

from pydantic import Field

from src.models.base import MissionBaseModel
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
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.models import (
    LLMCallResult,
    LLMCallStatus,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
)
from src.shared.llm.request import LLMRequest


class LLMServiceAttempt(MissionBaseModel):
    """Result summary for one provider-profile attempt."""

    profile_id: str
    provider_name: str
    model: str

    status: LLMCallStatus

    error_message: str | None = None


class LLMServiceResult(MissionBaseModel):
    """Final result returned by the central LLM service."""

    result: LLMCallResult

    selected_profile_id: str | None = None

    attempted_profile_ids: list[str] = Field(
        default_factory=list,
    )

    attempts: list[LLMServiceAttempt] = Field(
        default_factory=list,
    )

    used_failover: bool = False

    @property
    def is_success(self) -> bool:
        """Return whether a provider completed the request."""

        return self.result.is_success


AdapterResolver = Callable[
    [str],
    LLMProviderAdapter,
]


class LLMService:
    """
    Central entry point for production LLM calls.

    It coordinates profile selection, secret resolution,
    budget handling, provider creation, gateway execution,
    health updates and automatic failover.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        provider_factory: ProviderFactory,
        budget_service: ProviderBudgetService,
        gateway: LLMGateway,
        adapter_resolver: AdapterResolver | None = None,
    ) -> None:
        self.registry = registry
        self.provider_factory = provider_factory
        self.budget_service = budget_service
        self.gateway = gateway

        self.adapter_resolver = (
            adapter_resolver
            or provider_factory.create_llm_adapter
        )

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        """
        Execute an LLM request with automatic provider failover.

        When profile_ids is omitted, all usable LLM profiles
        are attempted in registry priority order.
        """

        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated LLM cost cannot be negative."
            )

        candidates = self._resolve_candidates(
            profile_ids
        )

        if not candidates:
            raise ValueError(
                "No usable LLM provider profiles are available."
            )

        attempted_profile_ids: list[str] = []
        attempts: list[LLMServiceAttempt] = []

        last_result: LLMCallResult | None = None

        for profile in candidates:
            attempted_profile_ids.append(
                profile.profile_id
            )

            budget_check = (
                self.budget_service.check_request(
                    profile.profile_id,
                    estimated_cost_usd,
                )
            )

            if not budget_check.allowed:
                blocked_result = LLMCallResult(
                    status=(
                        LLMCallStatus.BLOCKED_BY_BUDGET
                    ),
                    provider=request.provider,
                    model=(
                        profile.default_model
                        or request.model
                    ),
                    error_message=budget_check.reason,
                    metadata={
                        "profile_id": profile.profile_id,
                    },
                )

                attempts.append(
                    LLMServiceAttempt(
                        profile_id=profile.profile_id,
                        provider_name=(
                            profile.provider_name
                        ),
                        model=blocked_result.model,
                        status=blocked_result.status,
                        error_message=(
                            blocked_result.error_message
                        ),
                    )
                )

                last_result = blocked_result
                continue

            reserved = False

            if estimated_cost_usd > 0:
                self.budget_service.reserve(
                    profile.profile_id,
                    estimated_cost_usd,
                )
                reserved = True

            try:
                adapter = self.adapter_resolver(
                    profile.profile_id
                )

                model = (
                    profile.default_model.strip()
                    if profile.default_model
                    else request.model
                )

                provider_request = request.model_copy(
                    update={
                        "provider": adapter.provider,
                        "model": model,
                        "provider_profile_id": (
                            profile.profile_id
                        ),
                    }
                )

                operation = adapter.create_operation(
                    provider_request
                )

                result = self.gateway.call(
                    provider=adapter.provider,
                    model=model,
                    operation=operation,
                    expect_json=(
                        provider_request.expect_json
                    ),
                )

            except Exception as error:
                result = LLMCallResult(
                    status=LLMCallStatus.PROVIDER_ERROR,
                    provider=request.provider,
                    model=(
                        profile.default_model
                        or request.model
                    ),
                    error_message=(
                        f"{type(error).__name__}: {error}"
                    ),
                    metadata={
                        "profile_id": profile.profile_id,
                        "error_type": type(error).__name__,
                    },
                )

            result.metadata["profile_id"] = (
                profile.profile_id
            )

            attempts.append(
                LLMServiceAttempt(
                    profile_id=profile.profile_id,
                    provider_name=profile.provider_name,
                    model=result.model,
                    status=result.status,
                    error_message=result.error_message,
                )
            )

            last_result = result

            if result.is_success:
                actual_cost = (
                    result.usage.estimated_cost_usd
                )

                if reserved:
                    self.budget_service.adjust_reserved_cost(
                        profile.profile_id,
                        reserved_cost_usd=(
                            estimated_cost_usd
                        ),
                        actual_cost_usd=actual_cost,
                    )
                elif actual_cost > 0:
                    self.budget_service.reserve(
                        profile.profile_id,
                        actual_cost,
                    )

                self._set_health_status(
                    profile,
                    ProviderHealthStatus.HEALTHY,
                )

                return LLMServiceResult(
                    result=result,
                    selected_profile_id=(
                        profile.profile_id
                    ),
                    attempted_profile_ids=(
                        attempted_profile_ids
                    ),
                    attempts=attempts,
                    used_failover=(
                        len(attempted_profile_ids) > 1
                    ),
                )

            if reserved:
                self.budget_service.release(
                    profile.profile_id,
                    estimated_cost_usd,
                )

            self._set_health_status(
                profile,
                ProviderHealthStatus.DEGRADED,
            )

        if last_result is None:
            raise RuntimeError(
                "LLM service did not produce a result."
            )

        return LLMServiceResult(
            result=last_result,
            selected_profile_id=None,
            attempted_profile_ids=(
                attempted_profile_ids
            ),
            attempts=attempts,
            used_failover=(
                len(attempted_profile_ids) > 1
            ),
        )

    def _resolve_candidates(
        self,
        profile_ids: list[str] | None,
    ) -> list[ProviderProfile]:
        """Resolve ordered and usable LLM profiles."""

        if profile_ids is None:
            return self.registry.list_by_category(
                category=ProviderCategory.LLM,
                usable_only=True,
            )

        candidates: list[ProviderProfile] = []
        seen: set[str] = set()

        for profile_id in profile_ids:
            normalized_id = profile_id.strip()

            if not normalized_id:
                continue

            if normalized_id in seen:
                continue

            seen.add(normalized_id)

            profile = self.registry.get(
                normalized_id
            )

            if profile.category != ProviderCategory.LLM:
                raise ValueError(
                    "Failover profile is not an LLM "
                    f"provider: {normalized_id}"
                )

            if profile.usable:
                candidates.append(profile)

        return candidates

    def _set_health_status(
        self,
        profile: ProviderProfile,
        status: ProviderHealthStatus,
    ) -> None:
        """Update one profile health state."""

        current_profile = self.registry.get(
            profile.profile_id
        )

        updated_profile = current_profile.model_copy(
            update={
                "health_status": status,
            }
        )

        self.registry.register(
            updated_profile,
            replace=True,
        )