"""
A key saved in Provider Manager is never overwritten by .env at start, and a stored key marks its
profile usable without a click (2026-10-09, live).

The operator's old Anthropic key expired; they saved a new one in Provider Manager and the vault held it
- until the app restarted, when the runtime configuration loader copied CLAUDE_API_KEY from .env (still
the old key) over it, and every call failed with a 401. Separately, the health status is not saved, so
after each restart a profile was "unknown", the content steps refused it ("No usable LLM provider
profiles are available") and the operator had to click Test configuration every time.
"""

from __future__ import annotations

import logging

import pytest

from src.config.settings import Settings
from src.desktop.services import check_unknown_profiles_at_start
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.runtime_configuration_loader import RuntimeConfigurationLoader
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)

_REFERENCE = "secret://providers/provider.llm.anthropic/default"


def _manager() -> tuple[ProviderSecretManager, InMemorySecretStore]:
    store = InMemorySecretStore()

    return ProviderSecretManager(secret_store=store), store


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"MISSION_AUTOMATION_DRY_RUN": False}
    defaults.update(overrides)

    return Settings(**defaults)  # type: ignore[arg-type]


# ----------------------------------------------------------- the secret manager


def test_a_missing_key_is_created_even_when_asked_to_keep_an_existing_one() -> None:
    manager, _store = _manager()

    result = manager.create_secret(
        profile_id="provider.llm.anthropic",
        secret_value="env-key-12345",
        keep_existing=True,
    )

    assert result.created is True
    assert manager.resolve_secret(_REFERENCE) == "env-key-12345"


def test_an_existing_key_is_kept_when_asked_to() -> None:
    manager, _store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="saved-key-12345"
    )

    result = manager.create_secret(
        profile_id="provider.llm.anthropic",
        secret_value="env-key-12345",
        keep_existing=True,
    )

    assert manager.resolve_secret(_REFERENCE) == "saved-key-12345"
    assert (result.created, result.replaced) == (False, False)


def test_by_default_a_key_is_still_replaced() -> None:
    manager, _store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="old-key-12345"
    )

    result = manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="new-key-12345"
    )

    assert manager.resolve_secret(_REFERENCE) == "new-key-12345"
    assert result.replaced is True


def test_saving_a_key_in_provider_manager_still_replaces_it() -> None:
    manager, _store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="old-key-12345"
    )

    manager.replace_secret(
        secret_reference=_REFERENCE, new_secret_value="new-key-12345"
    )

    assert manager.resolve_secret(_REFERENCE) == "new-key-12345"


# ----------------------------------------------------------------- the .env loader


def test_the_env_key_fills_an_empty_vault() -> None:
    store = InMemorySecretStore()
    loader = RuntimeConfigurationLoader(
        settings=_settings(CLAUDE_API_KEY="env-key-12345"),
        secret_store=store,
        require_voice_provider=False,
    )

    loader.load()

    assert ProviderSecretManager(secret_store=store).resolve_secret(_REFERENCE) == (
        "env-key-12345"
    )


def test_a_key_saved_in_the_screen_is_not_overwritten_by_env_at_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager, store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="saved-key-12345"
    )
    loader = RuntimeConfigurationLoader(
        settings=_settings(CLAUDE_API_KEY="old-env-key-12345"),
        secret_store=store,
        require_voice_provider=False,
    )

    with caplog.at_level(logging.WARNING):
        configuration = loader.load()

    assert manager.resolve_secret(_REFERENCE) == "saved-key-12345"
    assert [p.profile_id for p in configuration.provider_profiles] == [
        "provider.llm.anthropic"
    ]
    assert "differs from the one in .env" in caplog.text
    assert (
        "old-env-key-12345" not in caplog.text and "saved-key-12345" not in caplog.text
    )


def test_a_matching_env_key_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    manager, store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="same-key-12345"
    )
    loader = RuntimeConfigurationLoader(
        settings=_settings(CLAUDE_API_KEY="same-key-12345"),
        secret_store=store,
        require_voice_provider=False,
    )

    with caplog.at_level(logging.WARNING):
        loader.load()

    assert "differs from the one in .env" not in caplog.text


# ----------------------------------------------------------- the start-up check


def _profile(
    profile_id: str = "provider.llm.anthropic",
    *,
    category: ProviderCategory = ProviderCategory.LLM,
    enabled: bool = True,
    health: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN,
    reference: str | None = _REFERENCE,
) -> ProviderProfile:
    fields: dict[str, object] = {
        "profile_id": profile_id,
        "display_name": profile_id,
        "provider_name": "anthropic",
        "category": category,
        "enabled": enabled,
        "health_status": health,
    }

    if category == ProviderCategory.EXTERNAL_UI_VIDEO:
        fields["browser_profile_reference"] = "profile-1"
    elif reference is not None:
        fields["secret_reference"] = reference

    return ProviderProfile(**fields)  # type: ignore[arg-type]


def _registry(*profiles: ProviderProfile) -> ProviderRegistry:
    registry = ProviderRegistry()

    for profile in profiles:
        registry.register(profile)

    return registry


def test_a_stored_key_makes_an_unknown_profile_usable_without_a_click() -> None:
    manager, _store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="key-value-12345"
    )
    registry = _registry(_profile())
    assert registry.get("provider.llm.anthropic").usable is False

    checked = check_unknown_profiles_at_start(registry, manager)

    assert checked == ["provider.llm.anthropic"]
    assert registry.get("provider.llm.anthropic").usable is True
    assert registry.get("provider.llm.anthropic").health_status == (
        ProviderHealthStatus.HEALTHY
    )


def test_a_profile_whose_key_is_missing_is_marked_misconfigured_not_usable() -> None:
    manager, _store = _manager()  # nothing stored
    registry = _registry(_profile())

    check_unknown_profiles_at_start(registry, manager)

    assert registry.get("provider.llm.anthropic").usable is False
    assert registry.get("provider.llm.anthropic").health_status != (
        ProviderHealthStatus.HEALTHY
    )


def test_a_profile_already_checked_is_left_alone() -> None:
    manager, _store = _manager()
    registry = _registry(_profile(health=ProviderHealthStatus.UNHEALTHY))

    assert check_unknown_profiles_at_start(registry, manager) == []
    assert registry.get("provider.llm.anthropic").health_status == (
        ProviderHealthStatus.UNHEALTHY
    )


def test_a_disabled_profile_is_skipped() -> None:
    manager, _store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="key-value-12345"
    )
    registry = _registry(_profile("disabled-one", enabled=False, reference=None))

    assert check_unknown_profiles_at_start(registry, manager) == []


def test_a_browser_account_profile_is_not_checked_by_key() -> None:
    manager, _store = _manager()
    registry = _registry(
        _profile("flow-account", category=ProviderCategory.EXTERNAL_UI_VIDEO)
    )

    assert check_unknown_profiles_at_start(registry, manager) == []
    assert registry.get("flow-account").health_status == ProviderHealthStatus.UNKNOWN


def test_every_key_category_is_checked_not_only_the_llm() -> None:
    manager, _store = _manager()
    manager.create_secret(profile_id="eleven", secret_value="key-value-12345")
    reference = "secret://providers/eleven/default"
    registry = _registry(
        _profile("voice-1", category=ProviderCategory.VOICE, reference=reference),
        _profile("music-1", category=ProviderCategory.MUSIC, reference=reference),
    )

    checked = check_unknown_profiles_at_start(registry, manager)

    assert sorted(checked) == ["music-1", "voice-1"]


def test_one_failing_check_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.desktop import services
    from src.services.health.provider_health_service import ProviderHealthService

    manager, _store = _manager()
    manager.create_secret(
        profile_id="provider.llm.anthropic", secret_value="key-value-12345"
    )
    registry = _registry(_profile("flaky-a"), _profile("flaky-b"))
    real = ProviderHealthService.check_profile
    calls: list[str] = []

    def flaky(self, profile_id, checker):  # type: ignore[no-untyped-def]
        calls.append(profile_id)

        if profile_id == "flaky-a":
            raise RuntimeError("boom")

        return real(self, profile_id, checker)

    monkeypatch.setattr(ProviderHealthService, "check_profile", flaky)

    checked = services.check_unknown_profiles_at_start(registry, manager)

    assert calls == ["flaky-a", "flaky-b"]
    assert checked == ["flaky-b"]
