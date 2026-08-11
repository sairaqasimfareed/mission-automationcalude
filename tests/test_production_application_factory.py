from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from src.models.provider_profile import (
    ProviderProfile,
)
from src.models.voice_profile import (
    VoiceProfile,
)
from src.providers.voice_provider import (
    VoiceProvider,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.mission_application_service import (
    MissionApplicationService,
)
from src.services.production_application_factory import (
    ProductionApplicationFactory,
    ProductionApplicationRuntime,
)
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.secrets.provider_secret_manager import (
    SecretStore,
)


def _provider_profile() -> ProviderProfile:
    """
    Create one minimal provider profile.

    Provider execution is intentionally not exercised by these
    composition tests.
    """

    return ProviderProfile.model_construct(
        profile_id="provider.test",
        display_name="Test Provider",
        provider_name="test",
    )


def _voice_profile() -> VoiceProfile:
    """Create one valid provider-independent voice profile."""

    return VoiceProfile(
        profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
        fallback_profile_id=None,
    )



def _secret_store() -> SecretStore:
    """
    Return a typed identity-only SecretStore dependency.

    SecretStore is an abstract/interface boundary. These tests verify
    dependency composition only and never execute secret-store behavior.
    """

    return cast(
        SecretStore,
        object(),
    )


def _voice_provider() -> VoiceProvider:
    """
    Return a typed identity-only voice provider.

    Voice generation itself is not executed in these composition tests.
    """

    return cast(
        VoiceProvider,
        object(),
    )


def _asset_workflow_service() -> SceneAssetWorkflowService:
    """
    Return a typed identity-only asset workflow dependency.

    Asset workflow behavior is covered by its dedicated service tests.
    """

    return cast(
        SceneAssetWorkflowService,
        object(),
    )


def _genre_timeline_service() -> GenreTimelinePipelineService:
    """
    Return a typed identity-only genre timeline dependency.

    Timeline behavior is covered independently by its dedicated tests.
    """

    return cast(
        GenreTimelinePipelineService,
        object(),
    )


def _factory(
    *,
    checkpoint_storage_root: str | Path | None = None,
    production_render_service: (
        ProductionRenderService | None
    ) = None,
) -> ProductionApplicationFactory:
    """Build one production application factory for composition tests."""

    return ProductionApplicationFactory(
        secret_store=_secret_store(),
        provider_profiles=[
            _provider_profile(),
        ],
        voice_profiles=[
            _voice_profile(),
        ],
        voice_providers=[
            _voice_provider(),
        ],
        genre_registry=(
            GenreProfileRegistryService
            .with_default_profiles()
        ),
        asset_workflow_service=(
            _asset_workflow_service()
        ),
        genre_timeline_service=(
            _genre_timeline_service()
        ),
        checkpoint_storage_root=(
            checkpoint_storage_root
        ),
        production_render_service=(
            production_render_service
        ),
    )


def test_build_returns_complete_runtime() -> None:
    runtime = _factory().build()

    assert isinstance(
        runtime,
        ProductionApplicationRuntime,
    )

    assert isinstance(
        runtime.application,
        MissionApplicationService,
    )

    assert (
        runtime.render_stage_factory
        .production_render_enabled
        is True
    )

    assert (
        runtime.render_stage_factory
        .render_service
        is None
    )

    assert (
        runtime.render_stage_factory
        .production_render_service
        is runtime.production_render_service
    )


def test_runtime_uses_shared_voice_registry() -> None:
    runtime = _factory().build()

    directive_service = (
        runtime.render_runtime_factory
        .voice_directive_generation_service
    )

    assert (
        directive_service
        .voice_profile_registry
        is runtime
        .voice_resolution_runtime
        .voice_profile_registry
    )


def test_build_application_returns_entrypoint() -> None:
    application = (
        _factory()
        .build_application()
    )

    assert isinstance(
        application,
        MissionApplicationService,
    )


def test_build_without_checkpoint_root_disables_persistence() -> None:
    runtime = _factory().build()

    assert (
        runtime.checkpoint_storage_service
        is None
    )

    assert (
        runtime.checkpoint_service
        is None
    )

    assert (
        runtime.resume_planner_service
        is None
    )


def test_build_with_checkpoint_root_enables_complete_checkpoint_graph(
    tmp_path: Path,
) -> None:
    runtime = _factory(
        checkpoint_storage_root=(
            tmp_path / "checkpoints"
        ),
    ).build()

    assert (
        runtime.checkpoint_storage_service
        is not None
    )

    assert (
        runtime.checkpoint_service
        is not None
    )

    assert (
        runtime.resume_planner_service
        is not None
    )

    assert (
        runtime
        .render_runtime_factory
        .checkpoint_storage_service
        is runtime
        .checkpoint_storage_service
    )

    assert (
        runtime
        .render_runtime_factory
        .checkpoint_service
        is runtime
        .checkpoint_service
    )

    assert (
        runtime
        .render_runtime_factory
        .resume_planner_service
        is runtime
        .resume_planner_service
    )


def test_factory_uses_production_settings_by_default() -> None:
    factory = _factory()

    assert (
        factory.advanced_settings.dry_run
        is False
    )


def test_factory_preserves_explicit_production_renderer() -> None:
    renderer = ProductionRenderService()

    runtime = _factory(
        production_render_service=renderer,
    ).build()

    assert (
        runtime.production_render_service
        is renderer
    )

    assert (
        runtime.render_stage_factory
        .production_render_service
        is renderer
    )


@pytest.mark.parametrize(
    (
        "provider_profiles",
        "voice_profiles",
        "voice_providers",
        "message",
    ),
    [
        (
            [],
            [
                _voice_profile(),
            ],
            [
                _voice_provider(),
            ],
            (
                "Production application requires "
                "at least one provider profile."
            ),
        ),
        (
            [
                _provider_profile(),
            ],
            [],
            [
                _voice_provider(),
            ],
            (
                "Production application requires "
                "at least one voice profile."
            ),
        ),
        (
            [
                _provider_profile(),
            ],
            [
                _voice_profile(),
            ],
            [],
            (
                "Production application requires "
                "at least one voice provider."
            ),
        ),
    ],
)
def test_factory_rejects_missing_required_runtime_configuration(
    provider_profiles: list[
        ProviderProfile
    ],
    voice_profiles: list[
        VoiceProfile
    ],
    voice_providers: list[
        VoiceProvider
    ],
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        ProductionApplicationFactory(
            secret_store=(
                _secret_store()
            ),
            provider_profiles=(
                provider_profiles
            ),
            voice_profiles=(
                voice_profiles
            ),
            voice_providers=(
                voice_providers
            ),
            genre_registry=(
                GenreProfileRegistryService
                .with_default_profiles()
            ),
            asset_workflow_service=(
                _asset_workflow_service()
            ),
            genre_timeline_service=(
                _genre_timeline_service()
            ),
        )


def test_each_build_creates_fresh_application_graph() -> None:
    factory = _factory()

    first = factory.build()
    second = factory.build()

    assert (
        first
        is not second
    )

    assert (
        first.application
        is not second.application
    )

    assert (
        first.infrastructure
        is not second.infrastructure
    )

    assert (
        first.voice_resolution_runtime
        is not second.voice_resolution_runtime
    )

    assert (
        first.voice_generation_service
        is not second.voice_generation_service
    )

    assert (
        first.render_stage_factory
        is not second.render_stage_factory
    )

    assert (
        first.render_runtime_factory
        is not second.render_runtime_factory
    )
