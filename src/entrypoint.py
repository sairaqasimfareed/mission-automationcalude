from __future__ import annotations

import sys
from pathlib import Path

from src.config.settings import Settings
from src.providers.music_provider import MusicProvider
from src.providers.sound_effect_provider import SoundEffectProvider
from src.providers.voice_provider import VoiceProvider
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
from src.services.scene_asset_and_timeline_infrastructure_factory import (
    SceneAssetAndTimelineInfrastructureFactory,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.secrets.provider_secret_manager import SecretStore
from src.services.startup_diagnostics import StartupDiagnosticsReporter


def build_production_runtime(
    *,
    asset_workflow_service: SceneAssetWorkflowService | None = None,
    genre_timeline_service: GenreTimelinePipelineService | None = None,
    voice_providers: list[VoiceProvider] | None = None,
    music_providers: list[MusicProvider] | None = None,
    sound_effect_providers: list[SoundEffectProvider] | None = None,
    local_asset_directories: list[str | Path] | None = None,
    checkpoint_storage_root: str | Path | None = None,
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

    asset_workflow_service and genre_timeline_service are built with
    local-first, dry-run-by-default defaults via
    SceneAssetAndTimelineInfrastructureFactory when omitted. Pass them
    explicitly to use different local asset directories or custom
    asset/stock providers.

    voice_providers overrides RuntimeConfigurationLoader's own
    dry-run-or-raise voice provider construction (it has no visibility
    into desktop-configured provider profiles); music_providers and
    sound_effect_providers are passed straight through to
    ProductionApplicationFactory, which already falls back to dry-run
    (or an empty, stage-skipping list outside dry-run) when omitted.
    Omitting all three reproduces today's behavior exactly.

    checkpoint_storage_root overrides RuntimeConfiguration's own value,
    which RuntimeConfigurationLoader always loads as None today (no
    environment-driven construction path exists for it yet). Without
    checkpoint persistence, a job that pauses for asset decisions
    (WAITING_FOR_USER) cannot be resumed - re-running execute() from
    scratch re-runs already-completed stages like voice generation
    against a job that already has voice tracks, which fails.
    """

    configuration = RuntimeConfigurationLoader(
        settings=settings,
        secret_store=secret_store,
    ).load()

    effective_checkpoint_storage_root = (
        Path(checkpoint_storage_root)
        if checkpoint_storage_root is not None
        else configuration.checkpoint_storage_root
    )

    RuntimeConfigurationValidator(
        secret_store=configuration.secret_store,
        provider_profiles=configuration.provider_profiles,
        voice_profiles=configuration.voice_profiles,
        checkpoint_storage_root=effective_checkpoint_storage_root,
    ).validate()

    if asset_workflow_service is None or genre_timeline_service is None:
        infrastructure_factory = SceneAssetAndTimelineInfrastructureFactory(
            local_asset_directories=local_asset_directories,
        )

        if asset_workflow_service is None:
            asset_workflow_service = (
                infrastructure_factory.build_scene_asset_workflow_service()
            )

        if genre_timeline_service is None:
            genre_timeline_service = (
                infrastructure_factory.build_genre_timeline_pipeline_service(
                    genre_registry=configuration.genre_registry,
                )
            )

    runtime = ProductionApplicationFactory(
        secret_store=configuration.secret_store,
        provider_profiles=configuration.provider_profiles,
        voice_profiles=configuration.voice_profiles,
        voice_providers=(
            voice_providers
            if voice_providers is not None
            else configuration.voice_providers
        ),
        music_providers=music_providers,
        sound_effect_providers=sound_effect_providers,
        genre_registry=configuration.genre_registry,
        asset_workflow_service=asset_workflow_service,
        genre_timeline_service=genre_timeline_service,
        advanced_settings=configuration.advanced_settings,
        checkpoint_storage_root=effective_checkpoint_storage_root,
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
    local_asset_directories: list[str | Path] | None = None,
    checkpoint_storage_root: str | Path | None = None,
    settings: Settings | None = None,
    secret_store: SecretStore | None = None,
) -> int:
    """
    Compose the full production runtime and report readiness.
    """

    try:
        runtime = build_production_runtime(
            local_asset_directories=local_asset_directories,
            checkpoint_storage_root=checkpoint_storage_root,
            settings=settings,
            secret_store=secret_store,
        )
    except ValueError as exc:
        print(f"Mission Automation startup check failed: {exc}", file=sys.stderr)

        return 1

    profiles = runtime.infrastructure.provider_registry.list_all()
    healthy_ids = [profile.profile_id for profile in profiles if profile.usable]
    unhealthy_ids = [profile.profile_id for profile in profiles if not profile.usable]

    print("Mission Automation startup check passed.")
    print(f"Healthy LLM providers: {', '.join(healthy_ids)}")

    if unhealthy_ids:
        print(f"Unhealthy LLM providers: {', '.join(unhealthy_ids)}")

    print("Full application runtime composed and ready (execute()/resume()).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
