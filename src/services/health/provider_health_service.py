from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.provider_profile import (
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)


class ProviderHealthChecker(Protocol):
    """Interface for lightweight provider connection checks."""

    def check(
        self,
        profile: ProviderProfile,
    ) -> tuple[bool, str]:
        """Return success state and a human-readable message."""
        ...


class ProviderHealthResult(MissionBaseModel):
    """Result of one provider health check."""

    profile_id: str
    status: ProviderHealthStatus
    healthy: bool

    message: str = ""

    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    latency_ms: int | None = Field(
        default=None,
        ge=0,
    )

    metadata: dict[str, str] = Field(
        default_factory=dict,
    )


class ProviderHealthService:
    """Checks and updates provider profile health states."""

    def __init__(
        self,
        registry: ProviderRegistry,
    ) -> None:
        self.registry = registry

    def check_profile(
        self,
        profile_id: str,
        checker: ProviderHealthChecker,
    ) -> ProviderHealthResult:
        """Run one health check and update the registry profile."""

        profile = self.registry.get(profile_id)

        if not profile.enabled:
            result = ProviderHealthResult(
                profile_id=profile.profile_id,
                status=ProviderHealthStatus.DISABLED,
                healthy=False,
                message="Provider profile is disabled.",
            )

            self._update_profile_status(
                profile=profile,
                status=result.status,
            )

            return result

        if not profile.secret_reference:
            result = ProviderHealthResult(
                profile_id=profile.profile_id,
                status=ProviderHealthStatus.MISCONFIGURED,
                healthy=False,
                message="Provider profile has no secret reference.",
            )

            self._update_profile_status(
                profile=profile,
                status=result.status,
            )

            return result

        try:
            healthy, message = checker.check(profile)
        except Exception as exc:
            result = ProviderHealthResult(
                profile_id=profile.profile_id,
                status=ProviderHealthStatus.UNHEALTHY,
                healthy=False,
                message=("Provider health check failed: " f"{type(exc).__name__}"),
                metadata={
                    "error_type": type(exc).__name__,
                },
            )

            self._update_profile_status(
                profile=profile,
                status=result.status,
            )

            return result

        status = (
            ProviderHealthStatus.HEALTHY if healthy else ProviderHealthStatus.UNHEALTHY
        )

        result = ProviderHealthResult(
            profile_id=profile.profile_id,
            status=status,
            healthy=healthy,
            message=message.strip(),
        )

        self._update_profile_status(
            profile=profile,
            status=status,
        )

        return result

    def mark_degraded(
        self,
        profile_id: str,
        *,
        message: str = "Provider is degraded.",
    ) -> ProviderHealthResult:
        """Manually mark a profile as degraded."""

        profile = self.registry.get(profile_id)

        result = ProviderHealthResult(
            profile_id=profile.profile_id,
            status=ProviderHealthStatus.DEGRADED,
            healthy=True,
            message=message,
        )

        self._update_profile_status(
            profile=profile,
            status=result.status,
        )

        return result

    def mark_unknown(
        self,
        profile_id: str,
    ) -> ProviderHealthResult:
        """Reset a profile health state to unknown."""

        profile = self.registry.get(profile_id)

        result = ProviderHealthResult(
            profile_id=profile.profile_id,
            status=ProviderHealthStatus.UNKNOWN,
            healthy=False,
            message="Provider health status was reset.",
        )

        self._update_profile_status(
            profile=profile,
            status=result.status,
        )

        return result

    def _update_profile_status(
        self,
        *,
        profile: ProviderProfile,
        status: ProviderHealthStatus,
    ) -> None:
        updated_profile = profile.model_copy(
            update={
                "health_status": status,
            }
        )

        self.registry.register(
            updated_profile,
            replace=True,
        )
