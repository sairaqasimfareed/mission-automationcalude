from __future__ import annotations

import sys

from src.config.settings import Settings
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructureFactory,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.health.provider_startup_validator import (
    ProviderStartupValidator,
)
from src.services.production_application_factory import (
    ProductionApplicationFactory,
    ProductionApplicationRuntime,
)
from src.services.runtime_configuration_loader import (
    RuntimeConfigurationLoader,
)
from src.services.runtime_configuration_validator import (
    RuntimeConfigurationValidator,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.secrets.provider_secret_manager import SecretStore
from src.services.startup_diagnostics import StartupDiagnosticsReporter


def build_production_runtime(
    *,
    asset_workflow_service: SceneAssetWorkflowService,
    genre_timeline_service: GenreTimelinePipelineService,
    settings: Settings | None = None,
    secret_store: SecretStore | None = None,
) -> ProductionApplicationRuntime:
    """
    Compose and validate one production Mission Automation runtime.

    This is the application's executable entrypoint boundary: it runs
    runtime-configuration loading (21.3), pre-flight configuration
    validation (21.5), composition-root construction (21.2), and
    provider startup validation (21.4), in that order, so a broken
    environment fails fast with an actionable error before any
    content generation is attempted.

    asset_workflow_service and genre_timeline_service must still be
    supplied by the caller: Mission Automation has no
    environment-variable-driven construction path for local asset
    infrastructure or genre/timeline wiring yet.
    """

    configuration = RuntimeConfigurationLoader(
        settings=settings,
        secret_store=secret_store,
    ).load()

    RuntimeConfigurationValidator(
        secret_store=configuration.secret_store,
        provider_profiles=configuration.provider_profiles,
        voice_profiles=configuration.voice_profiles,
        checkpoint_storage_root=configuration.checkpoint_storage_root,
    ).validate()

    runtime = ProductionApplicationFactory(
        secret_store=configuration.secret_store,
        provider_profiles=configuration.provider_profiles,
        voice_profiles=configuration.voice_profiles,
        voice_providers=configuration.voice_providers,
        genre_registry=configuration.genre_registry,
        asset_workflow_service=asset_workflow_service,
        genre_timeline_service=genre_timeline_service,
        advanced_settings=configuration.advanced_settings,
        checkpoint_storage_root=configuration.checkpoint_storage_root,
    ).build()

    validation_result = ProviderStartupValidator(
        runtime.infrastructure,
    ).validate()

    reporter = StartupDiagnosticsReporter()

    reporter.log_report(
        reporter.build_report(
            configuration=configuration,
            validation_result=validation_result,
        )
    )

    return runtime


def main(
    *,
    settings: Settings | None = None,
    secret_store: SecretStore | None = None,
) -> int:
    """
    Run standalone startup composition and report readiness.

    Local asset and genre/timeline infrastructure have no
    environment-driven construction path yet, so standalone execution
    cannot complete full composition. This entrypoint runs the parts
    that are fully environment-driven today - configuration loading,
    configuration validation, and provider startup validation - and
    reports the result, rather than crashing on a missing dependency
    it has no way to supply from the command line.
    """

    try:
        configuration = RuntimeConfigurationLoader(
            settings=settings,
            secret_store=secret_store,
        ).load()

        RuntimeConfigurationValidator(
            secret_store=configuration.secret_store,
            provider_profiles=configuration.provider_profiles,
            voice_profiles=configuration.voice_profiles,
            checkpoint_storage_root=configuration.checkpoint_storage_root,
        ).validate()

        infrastructure = ApplicationInfrastructureFactory(
            secret_store=configuration.secret_store,
        ).build(provider_profiles=configuration.provider_profiles)

        validation_result = ProviderStartupValidator(infrastructure).validate()

        reporter = StartupDiagnosticsReporter()

        report = reporter.build_report(
            configuration=configuration,
            validation_result=validation_result,
        )

        reporter.log_report(report)
    except ValueError as exc:
        print(f"Mission Automation startup check failed: {exc}", file=sys.stderr)

        return 1

    print("Mission Automation startup check passed.")
    print(f"Dry run: {report.dry_run}")
    print(f"Healthy LLM providers: {', '.join(report.healthy_provider_profile_ids)}")

    if report.unhealthy_provider_profile_ids:
        print(
            "Unhealthy LLM providers: "
            + ", ".join(report.unhealthy_provider_profile_ids)
        )

    print(
        "Note: asset_workflow_service and genre_timeline_service are not "
        "yet configurable from the environment, so the full application "
        "runtime cannot be composed from the command line. Use "
        "build_production_runtime() directly once those services are "
        "available."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
