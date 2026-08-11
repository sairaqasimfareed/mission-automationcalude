from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.models.advanced_settings import AdvancedSettings
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.voice_profile import VoiceProfile
from src.providers.dry_run_voice_provider import DryRunVoiceProvider
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.health.provider_health_service import (
    ProviderHealthResult,
)
from src.services.health.provider_startup_validator import (
    ProviderStartupValidationResult,
)
from src.services.runtime_configuration_loader import RuntimeConfiguration
from src.services.secrets.provider_secret_manager import InMemorySecretStore
from src.services.startup_diagnostics import (
    StartupDiagnosticsReport,
    StartupDiagnosticsReporter,
)


def _configuration(
    *,
    dry_run: bool = True,
    checkpoint_storage_root: Path | None = None,
) -> RuntimeConfiguration:
    return RuntimeConfiguration(
        secret_store=InMemorySecretStore(),
        provider_profiles=[
            ProviderProfile(
                profile_id="provider.llm.openai",
                display_name="OpenAI",
                provider_name="openai",
                category=ProviderCategory.LLM,
                enabled=True,
                secret_reference="secret://providers/provider.llm.openai/test",
            ),
        ],
        voice_profiles=[
            VoiceProfile(
                profile_id="voice.neutral_narrator",
                display_name="Neutral Narrator",
                fallback_profile_id=None,
            ),
        ],
        voice_providers=[DryRunVoiceProvider()],
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
        advanced_settings=AdvancedSettings(dry_run=dry_run),
        checkpoint_storage_root=checkpoint_storage_root,
    )


def _validation_result(
    *,
    healthy_ids: list[str],
    unhealthy_ids: list[str] | None = None,
) -> ProviderStartupValidationResult:
    results = [
        ProviderHealthResult(
            profile_id=profile_id,
            status=ProviderHealthStatus.HEALTHY,
            healthy=True,
        )
        for profile_id in healthy_ids
    ]

    results.extend(
        ProviderHealthResult(
            profile_id=profile_id,
            status=ProviderHealthStatus.UNHEALTHY,
            healthy=False,
        )
        for profile_id in (unhealthy_ids or [])
    )

    return ProviderStartupValidationResult(results=results)


def test_build_report_reflects_dry_run_and_provider_counts() -> None:
    configuration = _configuration(dry_run=True)
    validation_result = _validation_result(
        healthy_ids=["provider.llm.openai"],
    )

    report = StartupDiagnosticsReporter().build_report(
        configuration=configuration,
        validation_result=validation_result,
    )

    assert isinstance(report, StartupDiagnosticsReport)
    assert report.dry_run is True
    assert report.provider_profile_count == 1
    assert report.healthy_provider_profile_ids == ["provider.llm.openai"]
    assert report.unhealthy_provider_profile_ids == []


def test_build_report_separates_healthy_and_unhealthy_providers() -> None:
    configuration = _configuration()
    validation_result = _validation_result(
        healthy_ids=["provider.llm.openai"],
        unhealthy_ids=["provider.llm.broken"],
    )

    report = StartupDiagnosticsReporter().build_report(
        configuration=configuration,
        validation_result=validation_result,
    )

    assert report.healthy_provider_profile_ids == ["provider.llm.openai"]
    assert report.unhealthy_provider_profile_ids == ["provider.llm.broken"]


def test_build_report_includes_voice_and_genre_counts() -> None:
    configuration = _configuration()
    validation_result = _validation_result(healthy_ids=["provider.llm.openai"])

    report = StartupDiagnosticsReporter().build_report(
        configuration=configuration,
        validation_result=validation_result,
    )

    assert report.voice_profile_ids == ["voice.neutral_narrator"]
    assert report.voice_provider_names == ["dry_run"]
    assert report.genre_profile_count > 0


def test_build_report_checkpoint_persistence_flag(tmp_path: Path) -> None:
    without_checkpoint = StartupDiagnosticsReporter().build_report(
        configuration=_configuration(checkpoint_storage_root=None),
        validation_result=_validation_result(
            healthy_ids=["provider.llm.openai"],
        ),
    )

    with_checkpoint = StartupDiagnosticsReporter().build_report(
        configuration=_configuration(
            checkpoint_storage_root=tmp_path / "checkpoints",
        ),
        validation_result=_validation_result(
            healthy_ids=["provider.llm.openai"],
        ),
    )

    assert without_checkpoint.checkpoint_persistence_enabled is False
    assert with_checkpoint.checkpoint_persistence_enabled is True


def test_is_healthy_reflects_at_least_one_healthy_provider() -> None:
    healthy_report = StartupDiagnosticsReporter().build_report(
        configuration=_configuration(),
        validation_result=_validation_result(
            healthy_ids=["provider.llm.openai"],
        ),
    )

    unhealthy_report = StartupDiagnosticsReporter().build_report(
        configuration=_configuration(),
        validation_result=_validation_result(
            healthy_ids=[],
            unhealthy_ids=["provider.llm.broken"],
        ),
    )

    assert healthy_report.is_healthy is True
    assert unhealthy_report.is_healthy is False


def test_as_log_fields_never_includes_secret_values() -> None:
    report = StartupDiagnosticsReporter().build_report(
        configuration=_configuration(),
        validation_result=_validation_result(
            healthy_ids=["provider.llm.openai"],
        ),
    )

    fields = report.as_log_fields()

    serialized = str(fields)

    assert "secret://" not in serialized
    assert set(fields) == {
        "generated_at",
        "dry_run",
        "provider_profile_count",
        "healthy_provider_profile_ids",
        "unhealthy_provider_profile_ids",
        "voice_profile_ids",
        "voice_provider_names",
        "genre_profile_count",
        "checkpoint_persistence_enabled",
    }


def test_log_report_logs_structured_startup_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    report = StartupDiagnosticsReporter().build_report(
        configuration=_configuration(),
        validation_result=_validation_result(
            healthy_ids=["provider.llm.openai"],
        ),
    )

    with caplog.at_level(logging.INFO, logger="MissionAutomation"):
        StartupDiagnosticsReporter().log_report(report)

    messages = [record.message for record in caplog.records]

    assert any("startup diagnostics" in message for message in messages)
