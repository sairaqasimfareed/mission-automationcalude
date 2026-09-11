from __future__ import annotations

from src.desktop import services
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def _clear_caches() -> None:
    services.get_production_runtime.cache_clear()
    services.get_infrastructure.cache_clear()
    services.get_content_pipeline.cache_clear()
    services.get_render_runtime_factory.cache_clear()
    services.get_runtime_configuration.cache_clear()
    services.get_voice_profile_registry_service.cache_clear()


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


# --- 2026-09-11 real fix ("don't hardcode a voice per genre, I want
# it flexible"): _build_elevenlabs_voice_search_client() is the
# shared logic behind both get_elevenlabs_voice_search_client() (the
# GUI's manual "Suggest voices" button) and get_production_runtime()'s
# new DynamicVoiceSelectionService wiring - factored out so the latter
# doesn't have to call get_infrastructure()/get_production_runtime()
# from inside itself (which would recurse). ---


def _secret_manager_with(*, secret_value: str) -> tuple[ProviderSecretManager, str]:
    secret_manager = ProviderSecretManager(secret_store=InMemorySecretStore())
    result = secret_manager.create_secret(profile_id="voice", secret_value=secret_value)

    return secret_manager, result.secret_reference


def _voice_profile(
    *, provider_name: str, enabled: bool, secret_reference: str | None
) -> ProviderProfile:
    return ProviderProfile(
        profile_id="voice-profile",
        display_name="Voice Profile",
        provider_name=provider_name,
        category=ProviderCategory.VOICE,
        enabled=enabled,
        secret_reference=secret_reference,
    )


def test_build_elevenlabs_voice_search_client_resolves_a_real_key() -> None:
    secret_manager, secret_reference = _secret_manager_with(secret_value="real-key-123")
    profile = _voice_profile(
        provider_name="elevenlabs", enabled=True, secret_reference=secret_reference
    )

    client = services._build_elevenlabs_voice_search_client(
        voice_profiles=[profile], secret_manager=secret_manager
    )

    assert client is not None


def test_build_elevenlabs_voice_search_client_ignores_a_disabled_profile() -> None:
    secret_manager, secret_reference = _secret_manager_with(secret_value="real-key-123")
    profile = _voice_profile(
        provider_name="elevenlabs", enabled=False, secret_reference=secret_reference
    )

    client = services._build_elevenlabs_voice_search_client(
        voice_profiles=[profile], secret_manager=secret_manager
    )

    assert client is None


def test_build_elevenlabs_voice_search_client_ignores_a_different_provider() -> None:
    secret_manager, secret_reference = _secret_manager_with(secret_value="real-key-123")
    profile = _voice_profile(
        provider_name="openai", enabled=True, secret_reference=secret_reference
    )

    client = services._build_elevenlabs_voice_search_client(
        voice_profiles=[profile], secret_manager=secret_manager
    )

    assert client is None


def test_build_elevenlabs_voice_search_client_none_without_any_profile() -> None:
    secret_manager = ProviderSecretManager(secret_store=InMemorySecretStore())

    client = services._build_elevenlabs_voice_search_client(
        voice_profiles=[], secret_manager=secret_manager
    )

    assert client is None


# --- 2026-09-11 real fix, found live while verifying dynamic voice
# selection: RuntimeConfigurationLoader's own default voice_profiles
# is deliberately just [voice.neutral_narrator] (a minimal loader
# default, not meant as the real desktop set) - without
# _default_voice_profiles() supplying the full built-in set to both
# real call sites, every genre-specific voice_profile_id (e.g.
# "voice.horror_whisper") silently fell back to neutral_narrator in
# real generation, before any pin or dynamic search was ever
# consulted. ---


def test_default_voice_profiles_includes_genre_specific_profiles() -> None:
    profile_ids = {profile.profile_id for profile in services._default_voice_profiles()}

    assert "voice.horror_whisper" in profile_ids
    assert "voice.neutral_narrator" in profile_ids
    assert len(profile_ids) > 1


def test_voice_profile_registry_service_matches_default_voice_profiles() -> None:
    """
    Voice Manager's own registry must show every profile real
    generation would also resolve - the two must never silently
    diverge.
    """

    _clear_caches()

    registry_ids = {
        profile.profile_id
        for profile in services.get_voice_profile_registry_service().list_all()
    }
    default_ids = {profile.profile_id for profile in services._default_voice_profiles()}

    assert registry_ids == default_ids
    assert "voice.horror_whisper" in registry_ids


def test_production_runtime_resolves_a_genre_specific_voice_profile() -> None:
    """
    Real integration check: a genre-specific voice_profile_id must
    resolve to itself in real generation, not silently fall back to
    voice.neutral_narrator - the bug this fix closes.
    """

    _clear_caches()

    try:
        runtime = services.get_production_runtime()

        assert runtime.voice_resolution_runtime.voice_profile_registry.contains(
            "voice.horror_whisper"
        )
    finally:
        _clear_caches()
