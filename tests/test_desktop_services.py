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


def test_get_runtime_configuration_does_not_require_a_real_llm_or_voice_key(
    monkeypatch,
) -> None:
    """
    Real-world finding, 2026-09-12: a real operator hit this directly -
    the desktop app failed to even open its main window with "No
    production voice-provider adapter is configured", despite already
    having a real, working ElevenLabs setup, purely because this
    function's bare RuntimeConfigurationLoader() call never received
    the same require_llm_key=False/require_voice_provider=False
    relaxation get_production_runtime() already applies for the exact
    same reason (this desktop app always supplies its own real LLM/
    voice profiles a different way, never via env-var keys).
    MainWindow.__init__ only ever reads `.genre_registry` from this -
    a self-contained default with no external dependency at all - so
    neither requirement should ever be able to block it.
    """

    from src.config.settings import settings as real_settings

    monkeypatch.setattr(real_settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(real_settings, "CLAUDE_API_KEY", "")
    monkeypatch.setattr(real_settings, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(real_settings, "MISSION_AUTOMATION_DRY_RUN", False)

    _clear_caches()

    configuration = services.get_runtime_configuration()

    assert configuration.genre_registry is not None
    assert configuration.provider_profiles == []


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


def test_get_extracted_frame_asset_storage_service_is_shared_and_persistent() -> None:
    """
    Real-world finding, 2026-09-21: SceneVideoGenerationService used
    to be wired without frame_extraction_service/asset_storage_service
    at all in the desktop process - Phase 2/4/5's real visual-
    continuity/multi-clip-splitting features were fully built and
    real-world verified, but unreachable from the actual app. Also
    regression-tests that this is cached (not built fresh per call) -
    AssetIndex is explicitly in-memory only, so a reference extracted
    while generating scene 1 must still be resolvable when scene 2
    generates later, in a separate get_scene_video_generation_service()
    call.
    """

    services.get_extracted_frame_asset_storage_service.cache_clear()

    storage_service = services.get_extracted_frame_asset_storage_service()

    assert storage_service is services.get_extracted_frame_asset_storage_service()

    assert (
        storage_service.storage_root == services.EXTRACTED_FRAME_STORAGE_ROOT.resolve()
    )


def test_get_frame_extraction_service_is_shared() -> None:
    services.get_frame_extraction_service.cache_clear()

    frame_extraction_service = services.get_frame_extraction_service()

    assert frame_extraction_service is services.get_frame_extraction_service()


def test_get_scene_video_generation_service_wires_real_continuity_dependencies() -> (
    None
):
    """
    The whole point of the fix: a real caller must actually get
    frame_extraction_service/asset_storage_service wired in, using the
    SAME shared, cached instances every call - not silently reproduce
    the pre-fix "no continuity features at all" behavior.
    """

    _clear_caches()
    services.get_extracted_frame_asset_storage_service.cache_clear()
    services.get_frame_extraction_service.cache_clear()

    service = services.get_scene_video_generation_service()

    assert service._frame_extraction_service is (  # noqa: SLF001
        services.get_frame_extraction_service()
    )
    assert service._asset_storage_service is (  # noqa: SLF001
        services.get_extracted_frame_asset_storage_service()
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
