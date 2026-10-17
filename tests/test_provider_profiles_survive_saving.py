"""
Found live 2026-10-16: with dry run on, the registry holds only the dry-run placeholder (the operator's real
profiles are deliberately not registered), and a save used to write exactly the registry - so disabling the
placeholder erased every provider the operator had added. A save must never drop a stored profile that was
not deleted, and the placeholder is never stored.
"""

from __future__ import annotations

import sys

from src.config.settings import default_dry_run
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.services.provider_profile_management_service import (
    DRY_RUN_LLM_PROFILE_ID,
    ProviderProfileManagementService,
)
from src.services.registry.provider_profile_repository import (
    InMemoryProviderProfileRepository,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def _profile(profile_id: str, *, priority: int = 100, enabled: bool = False):  # type: ignore[no-untyped-def]
    return ProviderProfile(
        profile_id=profile_id,
        display_name=profile_id,
        provider_name="Anthropic",
        category=ProviderCategory.LLM,
        enabled=enabled,
        priority=priority,
        secret_reference="secret://test/ref" if enabled else None,
    )


def _service(stored: list[ProviderProfile], registered: list[ProviderProfile]):  # type: ignore[no-untyped-def]
    repository = InMemoryProviderProfileRepository(stored)
    registry = ProviderRegistry()
    for profile in registered:
        registry.register(profile)

    return (
        ProviderProfileManagementService(
            registry=registry,
            repository=repository,
            secret_manager=ProviderSecretManager(InMemorySecretStore()),
        ),
        repository,
    )


def _ids(repository: InMemoryProviderProfileRepository) -> set[str]:
    return {p.profile_id for p in repository.load_all()}


def test_disabling_the_placeholder_in_dry_run_keeps_every_stored_provider() -> None:
    stored = [_profile("claude", priority=1), _profile("haiku", priority=2)]
    placeholder = _profile(DRY_RUN_LLM_PROFILE_ID, enabled=True)
    service, repository = _service(stored, [placeholder])

    service.set_enabled(DRY_RUN_LLM_PROFILE_ID, False)

    assert _ids(repository) == {"claude", "haiku"}


def test_the_dry_run_placeholder_is_never_written_to_storage() -> None:
    service, repository = _service([], [_profile(DRY_RUN_LLM_PROFILE_ID, enabled=True)])

    service.set_enabled(DRY_RUN_LLM_PROFILE_ID, False)

    assert DRY_RUN_LLM_PROFILE_ID not in _ids(repository)


def test_a_save_still_stores_what_the_registry_holds() -> None:
    kept = _profile("claude")
    service, repository = _service([kept], [kept, _profile("extra")])

    service.set_health_status("extra", _any_health())

    assert _ids(repository) == {"claude", "extra"}


def test_deleting_a_profile_still_removes_it_from_storage() -> None:
    a, b = _profile("aaa"), _profile("bbb")
    service, repository = _service([a, b], [a, b])

    service.delete_profile("aaa")

    assert _ids(repository) == {"bbb"}


def test_a_deleted_profile_is_not_brought_back_by_a_later_save() -> None:
    a, b = _profile("aaa"), _profile("bbb")
    service, repository = _service([a, b], [a, b])

    service.delete_profile("aaa")
    service.set_health_status("bbb", _any_health())

    assert _ids(repository) == {"bbb"}


def _any_health():  # type: ignore[no-untyped-def]
    from src.models.provider_profile import ProviderHealthStatus

    return ProviderHealthStatus.HEALTHY


def test_development_defaults_to_dry_run_and_the_installed_app_to_real(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert default_dry_run() is True

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert default_dry_run() is False
