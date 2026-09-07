from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
    NoEligibleGoogleFlowAccountError,
)
from src.services.registry.provider_registry import ProviderRegistry


def _flow_profile(
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
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=enabled,
        priority=priority,
        health_status=health_status,
        browser_profile_reference=f"flow_profiles/{profile_id}",
        cooldown_until=cooldown_until,
    )


def test_selects_the_only_eligible_account() -> None:
    registry = ProviderRegistry(profiles=[_flow_profile("flow.primary")])
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "flow.primary"


def test_selects_by_priority_when_multiple_are_eligible() -> None:
    registry = ProviderRegistry(
        profiles=[
            _flow_profile("flow.secondary", priority=2),
            _flow_profile("flow.primary", priority=1),
        ]
    )
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "flow.primary"


def test_skips_a_disabled_account() -> None:
    registry = ProviderRegistry(
        profiles=[
            _flow_profile("flow.disabled", priority=1, enabled=False),
            _flow_profile("flow.backup", priority=2),
        ]
    )
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "flow.backup"


def test_skips_an_unhealthy_account() -> None:
    registry = ProviderRegistry(
        profiles=[
            _flow_profile(
                "flow.unhealthy",
                priority=1,
                health_status=ProviderHealthStatus.UNHEALTHY,
            ),
            _flow_profile("flow.backup", priority=2),
        ]
    )
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "flow.backup"


def test_skips_an_account_in_cooldown() -> None:
    registry = ProviderRegistry(
        profiles=[
            _flow_profile(
                "flow.cooldown",
                priority=1,
                cooldown_until=datetime.now(UTC) + timedelta(minutes=10),
            ),
            _flow_profile("flow.backup", priority=2),
        ]
    )
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "flow.backup"


def test_skips_an_account_at_its_in_flight_ceiling() -> None:
    registry = ProviderRegistry(
        profiles=[
            _flow_profile("flow.busy", priority=1),
            _flow_profile("flow.free", priority=2),
        ]
    )
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account(
        in_flight_counts={"flow.busy": 1},
        max_in_flight_per_account=1,
    )

    assert selected.profile_id == "flow.free"


def test_allows_an_account_under_a_higher_in_flight_ceiling() -> None:
    registry = ProviderRegistry(profiles=[_flow_profile("flow.primary", priority=1)])
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account(
        in_flight_counts={"flow.primary": 1},
        max_in_flight_per_account=2,
    )

    assert selected.profile_id == "flow.primary"


def test_raises_when_no_accounts_are_configured() -> None:
    router = GoogleFlowAccountRouterService(ProviderRegistry())

    with pytest.raises(NoEligibleGoogleFlowAccountError, match="No usable"):
        router.select_account()


def test_raises_when_every_account_is_at_its_ceiling() -> None:
    registry = ProviderRegistry(profiles=[_flow_profile("flow.primary")])
    router = GoogleFlowAccountRouterService(registry)

    with pytest.raises(NoEligibleGoogleFlowAccountError, match="in-flight"):
        router.select_account(in_flight_counts={"flow.primary": 1})


def test_ignores_non_flow_provider_categories() -> None:
    non_flow_profile = ProviderProfile(
        profile_id="llm-main",
        display_name="LLM Main",
        provider_name="OpenAI",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_reference="secret://llm-main",
    )
    registry = ProviderRegistry(
        profiles=[non_flow_profile, _flow_profile("flow.primary")]
    )
    router = GoogleFlowAccountRouterService(registry)

    selected = router.select_account()

    assert selected.profile_id == "flow.primary"


def test_rejects_a_ceiling_below_one() -> None:
    router = GoogleFlowAccountRouterService(ProviderRegistry())

    with pytest.raises(ValueError, match="at least 1"):
        router.select_account(max_in_flight_per_account=0)
