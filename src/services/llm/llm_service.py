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

    attempt_number: int = Field(
        ge=1,
    )

    profile_id: str
    provider_name: str
    model: str

    status: LLMCallStatus

    budget_reserved_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    actual_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

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
    all_providers_failed: bool = False

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

    Coordinates provider profiles, secrets, budgets,
    adapters, retries, health updates and failover.
    """

    FAILURE_COUNT_KEY = "llm_consecutive_failures"
    UNHEALTHY_FAILURE_THRESHOLD = 3

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

        self.adapter_resolver = adapter_resolver or provider_factory.create_llm_adapter

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        """Execute an LLM request with automatic failover."""

        if estimated_cost_usd < 0:
            raise ValueError("Estimated LLM cost cannot be negative.")

        candidates = self._resolve_candidates(profile_ids)

        if not candidates:
            raise ValueError("No usable LLM provider profiles are available.")

        attempted_profile_ids: list[str] = []
        attempts: list[LLMServiceAttempt] = []

        failure_messages: list[str] = []
        blocked_attempt_count = 0

        for attempt_number, profile in enumerate(
            candidates,
            start=1,
        ):
            attempted_profile_ids.append(profile.profile_id)

            model = self._resolve_model(
                profile=profile,
                request=request,
            )

            budget_check = self.budget_service.check_request(
                profile.profile_id,
                estimated_cost_usd,
            )

            if not budget_check.allowed:
                blocked_attempt_count += 1

                message = budget_check.reason

                attempts.append(
                    LLMServiceAttempt(
                        attempt_number=attempt_number,
                        profile_id=profile.profile_id,
                        provider_name=profile.provider_name,
                        model=model,
                        status=(LLMCallStatus.BLOCKED_BY_BUDGET),
                        error_message=message,
                    )
                )

                failure_messages.append(f"{profile.profile_id}: {message}")

                continue

            reserved = False

            if estimated_cost_usd > 0:
                self.budget_service.reserve(
                    profile.profile_id,
                    estimated_cost_usd,
                )
                reserved = True

            try:
                adapter = self.adapter_resolver(profile.profile_id)

                provider_request = request.model_copy(
                    update={
                        "provider": adapter.provider,
                        "model": model,
                        "provider_profile_id": (profile.profile_id),
                    }
                )

                operation = adapter.create_operation(provider_request)

                result = self.gateway.call(
                    provider=adapter.provider,
                    model=model,
                    operation=operation,
                    expect_json=(provider_request.expect_json),
                )

            except Exception as error:
                result = LLMCallResult(
                    status=LLMCallStatus.PROVIDER_ERROR,
                    provider=request.provider,
                    model=model,
                    error_message=(f"{type(error).__name__}: {error}"),
                    metadata={
                        "profile_id": profile.profile_id,
                        "error_type": type(error).__name__,
                    },
                )

            result.metadata["profile_id"] = profile.profile_id

            actual_cost = result.usage.estimated_cost_usd

            if result.is_success:
                accounting_warning = self._finalize_successful_cost(
                    profile_id=profile.profile_id,
                    reserved=reserved,
                    reserved_cost_usd=(estimated_cost_usd),
                    actual_cost_usd=actual_cost,
                )

                if accounting_warning is not None:
                    result.warnings.append(accounting_warning)

                    result.metadata["budget_accounting_warning"] = accounting_warning

                self._record_success(profile.profile_id)

                attempts.append(
                    LLMServiceAttempt(
                        attempt_number=attempt_number,
                        profile_id=profile.profile_id,
                        provider_name=profile.provider_name,
                        model=result.model,
                        status=result.status,
                        budget_reserved_usd=(estimated_cost_usd if reserved else 0.0),
                        actual_cost_usd=actual_cost,
                    )
                )

                return LLMServiceResult(
                    result=result,
                    selected_profile_id=(profile.profile_id),
                    attempted_profile_ids=(attempted_profile_ids),
                    attempts=attempts,
                    used_failover=attempt_number > 1,
                    all_providers_failed=False,
                )

            if reserved:
                self.budget_service.release(
                    profile.profile_id,
                    estimated_cost_usd,
                )

            self._record_failure(profile.profile_id)

            error_message = result.error_message or "Provider call failed."

            failure_messages.append(f"{profile.profile_id}: {error_message}")

            attempts.append(
                LLMServiceAttempt(
                    attempt_number=attempt_number,
                    profile_id=profile.profile_id,
                    provider_name=profile.provider_name,
                    model=result.model,
                    status=result.status,
                    budget_reserved_usd=(estimated_cost_usd if reserved else 0.0),
                    actual_cost_usd=actual_cost,
                    error_message=error_message,
                )
            )

        final_status = (
            LLMCallStatus.BLOCKED_BY_BUDGET
            if blocked_attempt_count == len(candidates)
            else LLMCallStatus.PROVIDER_ERROR
        )

        consolidated_message = (
            "All configured LLM provider attempts failed. "
            + " | ".join(failure_messages)
        )

        final_result = LLMCallResult(
            status=final_status,
            provider=request.provider,
            model=request.model,
            error_message=consolidated_message,
            metadata={
                "attempted_profile_ids": (",".join(attempted_profile_ids)),
                "attempt_count": len(attempts),
                "all_providers_failed": True,
            },
        )

        return LLMServiceResult(
            result=final_result,
            selected_profile_id=None,
            attempted_profile_ids=attempted_profile_ids,
            attempts=attempts,
            used_failover=len(attempts) > 1,
            all_providers_failed=True,
        )

    def _resolve_candidates(
        self,
        profile_ids: list[str] | None,
    ) -> list[ProviderProfile]:
        """Resolve ordered, unique and usable LLM profiles."""

        if profile_ids is None:
            return self.registry.list_by_category(
                category=ProviderCategory.LLM,
                usable_only=True,
            )

        candidates: list[ProviderProfile] = []
        seen: set[str] = set()

        for raw_profile_id in profile_ids:
            normalized_id = raw_profile_id.strip()

            if not normalized_id:
                continue

            if normalized_id in seen:
                continue

            seen.add(normalized_id)

            if not self.registry.contains(normalized_id):
                raise KeyError(
                    "Failover provider profile is not " f"registered: {normalized_id}"
                )

            profile = self.registry.get(normalized_id)

            if profile.category != ProviderCategory.LLM:
                raise ValueError(
                    "Failover profile is not an LLM " f"provider: {normalized_id}"
                )

            if profile.usable:
                candidates.append(profile)

        return candidates

    @staticmethod
    def _resolve_model(
        *,
        profile: ProviderProfile,
        request: LLMRequest,
    ) -> str:
        """Resolve the model for one provider attempt."""

        if profile.default_model is not None and profile.default_model.strip():
            return profile.default_model.strip()

        return request.model

    def _finalize_successful_cost(
        self,
        *,
        profile_id: str,
        reserved: bool,
        reserved_cost_usd: float,
        actual_cost_usd: float,
    ) -> str | None:
        """Replace the reservation with actual provider cost."""

        if reserved:
            try:
                self.budget_service.adjust_reserved_cost(
                    profile_id,
                    reserved_cost_usd=(reserved_cost_usd),
                    actual_cost_usd=actual_cost_usd,
                )
                return None

            except ValueError as error:
                current_profile = self.registry.get(profile_id)

                reservation_missing = (
                    current_profile.daily_spent_usd < reserved_cost_usd
                    or current_profile.monthly_spent_usd < reserved_cost_usd
                )

                if reservation_missing:
                    try:
                        self.budget_service.reserve(
                            profile_id,
                            reserved_cost_usd,
                        )
                    except ValueError:
                        pass

                return "Actual provider cost could not be fully " f"recorded: {error}"

        if actual_cost_usd <= 0:
            return None

        try:
            self.budget_service.reserve(
                profile_id,
                actual_cost_usd,
            )
            return None

        except ValueError as error:
            return "Actual provider cost could not be recorded: " f"{error}"

    def _record_success(
        self,
        profile_id: str,
    ) -> None:
        """Mark a provider healthy and reset failures."""

        profile = self.registry.get(profile_id)

        metadata = dict(profile.metadata)
        metadata[self.FAILURE_COUNT_KEY] = "0"

        updated_profile = profile.model_copy(
            update={
                "health_status": (ProviderHealthStatus.HEALTHY),
                "metadata": metadata,
            }
        )

        self.registry.register(
            updated_profile,
            replace=True,
        )

    def _record_failure(
        self,
        profile_id: str,
    ) -> None:
        """Increment failures and escalate provider health."""

        profile = self.registry.get(profile_id)

        metadata = dict(profile.metadata)

        raw_failure_count = metadata.get(
            self.FAILURE_COUNT_KEY,
            "0",
        )

        try:
            previous_failure_count = int(raw_failure_count)
        except ValueError:
            previous_failure_count = 0

        failure_count = previous_failure_count + 1

        metadata[self.FAILURE_COUNT_KEY] = str(failure_count)

        status = (
            ProviderHealthStatus.UNHEALTHY
            if failure_count >= self.UNHEALTHY_FAILURE_THRESHOLD
            else ProviderHealthStatus.DEGRADED
        )

        updated_profile = profile.model_copy(
            update={
                "health_status": status,
                "metadata": metadata,
            }
        )

        self.registry.register(
            updated_profile,
            replace=True,
        )
