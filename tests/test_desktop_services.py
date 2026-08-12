from __future__ import annotations

from src.desktop import services
from src.models.provider_profile import ProviderHealthStatus


def test_get_infrastructure_validates_provider_health() -> None:
    """
    Regression test: get_infrastructure() must run
    ProviderStartupValidator, or every provider profile's
    health_status stays UNKNOWN forever and ProviderProfile.usable is
    always False, making every real LLM call fail with "No usable LLM
    provider profiles are available" - a bug found by exercising the
    desktop app's project-creation flow end to end.
    """

    services.get_infrastructure.cache_clear()
    services.get_runtime_configuration.cache_clear()

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
    services.get_infrastructure.cache_clear()
    services.get_runtime_configuration.cache_clear()
    services.get_content_pipeline.cache_clear()

    content_pipeline = services.get_content_pipeline()

    assert content_pipeline.research_pipeline is not None
    assert content_pipeline.script_pipeline is not None
