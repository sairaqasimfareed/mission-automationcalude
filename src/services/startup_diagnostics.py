from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.services.health.provider_startup_validator import (
    ProviderStartupValidationResult,
)
from src.services.runtime_configuration_loader import RuntimeConfiguration
from src.shared.logger import logger


@dataclass(frozen=True, slots=True)
class StartupDiagnosticsReport:
    """
    Structured, secret-free summary of one application startup.

    Only counts, identifiers, and non-sensitive configuration flags
    are captured here - never a resolved secret value.
    """

    generated_at: datetime
    dry_run: bool
    provider_profile_count: int
    healthy_provider_profile_ids: list[str]
    unhealthy_provider_profile_ids: list[str]
    voice_profile_ids: list[str]
    voice_provider_names: list[str]
    genre_profile_count: int
    checkpoint_persistence_enabled: bool

    @property
    def is_healthy(self) -> bool:
        """Return whether at least one provider passed startup validation."""

        return len(self.healthy_provider_profile_ids) > 0

    def as_log_fields(self) -> dict[str, object]:
        """Return a flat, secret-free mapping suitable for logging."""

        return {
            "generated_at": self.generated_at.isoformat(),
            "dry_run": self.dry_run,
            "provider_profile_count": self.provider_profile_count,
            "healthy_provider_profile_ids": self.healthy_provider_profile_ids,
            "unhealthy_provider_profile_ids": self.unhealthy_provider_profile_ids,
            "voice_profile_ids": self.voice_profile_ids,
            "voice_provider_names": self.voice_provider_names,
            "genre_profile_count": self.genre_profile_count,
            "checkpoint_persistence_enabled": self.checkpoint_persistence_enabled,
        }


class StartupDiagnosticsReporter:
    """
    Build and log a structured startup diagnostics report.

    This never inspects or logs a resolved secret value: only
    configuration counts, provider/profile identifiers, and
    non-sensitive flags derived from a loaded RuntimeConfiguration and
    a completed ProviderStartupValidationResult.
    """

    def build_report(
        self,
        *,
        configuration: RuntimeConfiguration,
        validation_result: ProviderStartupValidationResult,
    ) -> StartupDiagnosticsReport:
        """Build one startup diagnostics report."""

        healthy_ids = set(validation_result.healthy_profile_ids)

        unhealthy_ids = [
            result.profile_id
            for result in validation_result.results
            if result.profile_id not in healthy_ids
        ]

        return StartupDiagnosticsReport(
            generated_at=datetime.now(UTC),
            dry_run=configuration.advanced_settings.dry_run,
            provider_profile_count=len(configuration.provider_profiles),
            healthy_provider_profile_ids=list(validation_result.healthy_profile_ids),
            unhealthy_provider_profile_ids=unhealthy_ids,
            voice_profile_ids=[
                profile.profile_id for profile in configuration.voice_profiles
            ],
            voice_provider_names=[
                provider.provider_name for provider in configuration.voice_providers
            ],
            genre_profile_count=len(configuration.genre_registry.list_all()),
            checkpoint_persistence_enabled=(
                configuration.checkpoint_storage_root is not None
            ),
        )

    def log_report(self, report: StartupDiagnosticsReport) -> None:
        """Log the report as one structured startup event."""

        logger.info(
            "Mission Automation startup diagnostics: %s",
            report.as_log_fields(),
        )
