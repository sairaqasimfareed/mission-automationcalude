from __future__ import annotations

from src.desktop import services
from src.models.provider_profile import ProviderHealthStatus


def _clear_caches() -> None:
    services.get_production_runtime.cache_clear()
    services.get_infrastructure.cache_clear()
    services.get_content_pipeline.cache_clear()
    services.get_render_runtime_factory.cache_clear()
    services.get_runtime_configuration.cache_clear()


def test_get_infrastructure_validates_provider_health() -> None:
    """
    Regression test: the production runtime must run
    ProviderStartupValidator, or every provider profile's
    health_status stays UNKNOWN forever and ProviderProfile.usable is
    always False, making every real LLM call fail with "No usable LLM
    provider profiles are available" - a bug found by exercising the
    desktop app's project-creation flow end to end.
    """

    _clear_caches()

    infrastructure = services.get_infrastructure()

    profiles = infrastructure.provider_registry.list_all()

    assert profiles

    assert any(
        profile.health_status
        in {ProviderHealthStatus.HEALTHY, ProviderHealthStatus.DEGRADED}
        for profile in profiles
    )

    assert any(profile.usable for profile in profiles)


def test_get_content_pipeline_uses_validated_infrastructure() -> None:
    _clear_caches()

    content_pipeline = services.get_content_pipeline()

    assert content_pipeline.research_pipeline is not None
    assert content_pipeline.script_pipeline is not None


def test_get_render_runtime_factory_is_shared_with_content_pipeline() -> None:
    """
    Regression test: desktop must build render infrastructure through
    the same production runtime as content_pipeline, not a second,
    separate composition path with its own provider infrastructure.
    """

    _clear_caches()

    render_runtime_factory = services.get_render_runtime_factory()

    assert render_runtime_factory is (
        services.get_production_runtime().application.render_runtime_factory
    )


def test_get_final_export_service_is_ready() -> None:
    _clear_caches()

    final_export_service = services.get_final_export_service()

    assert final_export_service.packaging_service is not None
    assert final_export_service.validation_service is not None
