from __future__ import annotations

from src.providers.google_flow.locators import (
    VERIFIED_DURATIONS_SECONDS,
    clamp_to_verified_duration,
)


def test_clamp_to_verified_duration_returns_an_exact_match_unchanged() -> None:
    for verified in VERIFIED_DURATIONS_SECONDS:
        assert clamp_to_verified_duration(float(verified)) == verified


def test_clamp_to_verified_duration_rounds_up_to_the_next_verified_value() -> None:
    assert clamp_to_verified_duration(5.0) == 6
    assert clamp_to_verified_duration(5.5) == 6
    assert clamp_to_verified_duration(7.0) == 8
    assert clamp_to_verified_duration(7.5) == 8


def test_clamp_to_verified_duration_never_rounds_below_the_request() -> None:
    for requested in (4.1, 4.9, 6.1, 6.9):
        clamped = clamp_to_verified_duration(requested)
        assert clamped >= requested


def test_clamp_to_verified_duration_clamps_a_value_above_the_verified_range() -> None:
    assert clamp_to_verified_duration(18.0) == 8


def test_clamp_to_verified_duration_clamps_a_value_below_the_verified_range() -> None:
    assert clamp_to_verified_duration(1.0) == 4
