from __future__ import annotations

from src.models.production_handoff import (
    ProductionHandoffState,
    ProductionHandoffStatus,
)


def test_is_ready_true_only_for_package_ready() -> None:
    status = ProductionHandoffStatus(state=ProductionHandoffState.PACKAGE_READY)

    assert status.is_ready is True


def test_is_ready_false_for_locked() -> None:
    status = ProductionHandoffStatus(state=ProductionHandoffState.LOCKED)

    assert status.is_ready is False


def test_is_ready_false_for_building_package() -> None:
    status = ProductionHandoffStatus(state=ProductionHandoffState.BUILDING_PACKAGE)

    assert status.is_ready is False


def test_is_ready_false_for_blocked() -> None:
    status = ProductionHandoffStatus(
        state=ProductionHandoffState.BLOCKED, blocked_reason="No script lock exists."
    )

    assert status.is_ready is False
    assert status.blocked_reason == "No script lock exists."


def test_locked_script_hash_is_optional() -> None:
    status = ProductionHandoffStatus(state=ProductionHandoffState.LOCKED)

    assert status.locked_script_hash is None
