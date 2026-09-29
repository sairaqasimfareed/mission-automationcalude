from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.muse_account_router_service import (
    MuseAccountRouterService,
    NoEligibleMuseAccountError,
)
from src.services.registry.provider_registry import ProviderRegistry


def _muse_profile(
    profile_id: str,
    *,
    priority: int = 100,
    enabled: bool = True,
    health_status: ProviderHealthStatus = ProviderHealthStatus.HEALTHY,
    cooldown_until: datetime | None = None,
) -> ProviderProfile:
    return ProviderProfile(
        profile_id=profile_id,
        display_name=profile_id,
        provider_name="Muse",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=enabled,
        priority=priority,
        health_status=health_status,
        browser_profile_reference=f"muse_profiles/{profile_id}",
        cooldown_until=cooldown_until,
    )


def test_selects_the_only_eligible_account() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile("muse.primary")])
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.primary"


def test_selects_by_priority_when_multiple_are_eligible() -> None:
    registry = ProviderRegistry(
        profiles=[
            _muse_profile("muse.secondary", priority=2),
            _muse_profile("muse.primary", priority=1),
        ]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.primary"


def test_skips_a_disabled_account() -> None:
    registry = ProviderRegistry(
        profiles=[
            _muse_profile("muse.disabled", priority=1, enabled=False),
            _muse_profile("muse.backup", priority=2),
        ]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.backup"


def test_skips_an_unhealthy_account() -> None:
    registry = ProviderRegistry(
        profiles=[
            _muse_profile(
                "muse.unhealthy",
                priority=1,
                health_status=ProviderHealthStatus.UNHEALTHY,
            ),
            _muse_profile("muse.backup", priority=2),
        ]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.backup"


def test_skips_an_account_in_cooldown() -> None:
    registry = ProviderRegistry(
        profiles=[
            _muse_profile(
                "muse.cooldown",
                priority=1,
                cooldown_until=datetime.now(UTC) + timedelta(minutes=10),
            ),
            _muse_profile("muse.backup", priority=2),
        ]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.backup"


def test_skips_an_account_at_its_in_flight_ceiling() -> None:
    registry = ProviderRegistry(
        profiles=[
            _muse_profile("muse.busy", priority=1),
            _muse_profile("muse.free", priority=2),
        ]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account(
        in_flight_counts={"muse.busy": 1},
        max_in_flight_per_account=1,
    )

    assert selected.profile_id == "muse.free"


def test_allows_an_account_under_a_higher_in_flight_ceiling() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile("muse.primary", priority=1)])
    router = MuseAccountRouterService(registry)

    selected = router.select_account(
        in_flight_counts={"muse.primary": 1},
        max_in_flight_per_account=2,
    )

    assert selected.profile_id == "muse.primary"


def test_raises_when_no_accounts_are_configured() -> None:
    router = MuseAccountRouterService(ProviderRegistry())

    with pytest.raises(NoEligibleMuseAccountError, match="No usable"):
        router.select_account()


def test_raises_when_every_account_is_at_its_ceiling() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile("muse.primary")])
    router = MuseAccountRouterService(registry)

    with pytest.raises(NoEligibleMuseAccountError, match="in-flight"):
        router.select_account(in_flight_counts={"muse.primary": 1})


def test_ignores_non_muse_provider_categories() -> None:
    non_muse_profile = ProviderProfile(
        profile_id="llm-main",
        display_name="LLM Main",
        provider_name="OpenAI",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_reference="secret://llm-main",
    )
    registry = ProviderRegistry(
        profiles=[non_muse_profile, _muse_profile("muse.primary")]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.primary"


def test_ignores_a_different_provider_sharing_external_ui_video_category() -> None:
    """
    Same real-world finding as Google Flow's own router test:
    ProviderCategory.EXTERNAL_UI_VIDEO covers any browser-driven video
    provider - a Google Flow account profile registers under this same
    category, so this router must not accidentally select it.
    """

    flow_profile = ProviderProfile(
        profile_id="flow.primary",
        display_name="Flow Primary",
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        browser_profile_reference="flow_profiles/flow.primary",
    )
    registry = ProviderRegistry(
        profiles=[flow_profile, _muse_profile("muse.primary", priority=1)]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "muse.primary"


def test_raises_when_only_a_different_external_ui_video_provider_is_registered() -> (
    None
):
    flow_profile = ProviderProfile(
        profile_id="flow.primary",
        display_name="Flow Primary",
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        browser_profile_reference="flow_profiles/flow.primary",
    )
    registry = ProviderRegistry(profiles=[flow_profile])
    router = MuseAccountRouterService(registry)

    with pytest.raises(NoEligibleMuseAccountError, match="No usable"):
        router.select_account()


def test_preferred_profile_id_selects_that_exact_account() -> None:
    registry = ProviderRegistry(
        profiles=[
            _muse_profile("muse.primary", priority=1),
            _muse_profile("muse.backup", priority=2),
        ]
    )
    router = MuseAccountRouterService(registry)

    selected = router.select_account(preferred_profile_id="muse.backup")

    assert selected.profile_id == "muse.backup"


def test_preferred_profile_id_raises_a_clear_error_when_unregistered() -> None:
    router = MuseAccountRouterService(ProviderRegistry())

    with pytest.raises(NoEligibleMuseAccountError, match="not registered"):
        router.select_account(preferred_profile_id="muse.ghost")


def test_preferred_profile_id_raises_when_it_belongs_to_a_different_provider() -> None:
    flow_profile = ProviderProfile(
        profile_id="flow.primary",
        display_name="Flow Primary",
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        browser_profile_reference="flow_profiles/flow.primary",
    )
    registry = ProviderRegistry(profiles=[flow_profile])
    router = MuseAccountRouterService(registry)

    with pytest.raises(NoEligibleMuseAccountError, match="not a Muse"):
        router.select_account(preferred_profile_id="flow.primary")


def test_preferred_profile_id_raises_when_not_usable() -> None:
    registry = ProviderRegistry(
        profiles=[_muse_profile("muse.disabled", enabled=False)]
    )
    router = MuseAccountRouterService(registry)

    with pytest.raises(NoEligibleMuseAccountError, match="not currently usable"):
        router.select_account(preferred_profile_id="muse.disabled")


def test_preferred_profile_id_raises_when_at_its_in_flight_ceiling() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile("muse.primary")])
    router = MuseAccountRouterService(registry)

    with pytest.raises(NoEligibleMuseAccountError, match="in-flight attempt"):
        router.select_account(
            preferred_profile_id="muse.primary",
            in_flight_counts={"muse.primary": 1},
        )


def test_rejects_a_ceiling_below_one() -> None:
    router = MuseAccountRouterService(ProviderRegistry())

    with pytest.raises(ValueError, match="at least 1"):
        router.select_account(max_in_flight_per_account=0)
