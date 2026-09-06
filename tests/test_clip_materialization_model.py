from __future__ import annotations

from src.models.clip_materialization import ClipMaterializationStatus


def _status(**overrides: object) -> ClipMaterializationStatus:
    base: dict[str, object] = dict(
        total_clips=3,
        ready_clips=3,
        missing_clips=0,
        stale_clips=0,
        traced_to_prompt_clips=3,
        planned_duration_seconds=24.0,
        target_duration_seconds=24.0,
        total_estimated_cost=0.0,
    )
    base.update(overrides)
    return ClipMaterializationStatus(**base)


def test_duration_delta_seconds_computes_difference() -> None:
    status = _status(planned_duration_seconds=30.0, target_duration_seconds=24.0)

    assert status.duration_delta_seconds == 6.0


def test_is_fully_traced_true_when_every_clip_traced() -> None:
    status = _status(total_clips=3, traced_to_prompt_clips=3)

    assert status.is_fully_traced is True


def test_is_fully_traced_false_when_some_clips_untraced() -> None:
    status = _status(total_clips=3, traced_to_prompt_clips=2)

    assert status.is_fully_traced is False


def test_is_fully_traced_false_when_no_clips_exist() -> None:
    status = _status(total_clips=0, traced_to_prompt_clips=0)

    assert status.is_fully_traced is False


def test_is_ready_for_fulfillment_true_when_all_ready_and_fresh() -> None:
    status = _status(missing_clips=0, stale_clips=0)

    assert status.is_ready_for_fulfillment is True


def test_is_ready_for_fulfillment_false_with_missing_clips() -> None:
    status = _status(missing_clips=1)

    assert status.is_ready_for_fulfillment is False


def test_is_ready_for_fulfillment_false_with_stale_clips() -> None:
    status = _status(stale_clips=1)

    assert status.is_ready_for_fulfillment is False


def test_is_ready_for_fulfillment_false_when_no_clips_exist() -> None:
    status = _status(total_clips=0)

    assert status.is_ready_for_fulfillment is False


# --- Post-Script-Approval Production Plan, Phase 6: Fulfillment Budget Gate ---


def test_zero_budget_means_no_cap_configured() -> None:
    status = _status(maximum_visual_budget=0.0, total_estimated_cost=1000.0)

    assert status.has_budget_cap is False
    assert status.remaining_budget is None
    assert status.is_over_budget is False


def test_within_budget_is_not_over_budget() -> None:
    status = _status(maximum_visual_budget=100.0, total_estimated_cost=40.0)

    assert status.has_budget_cap is True
    assert status.remaining_budget == 60.0
    assert status.is_over_budget is False


def test_exceeding_budget_is_over_budget() -> None:
    status = _status(maximum_visual_budget=100.0, total_estimated_cost=150.0)

    assert status.remaining_budget == -50.0
    assert status.is_over_budget is True


def test_exactly_at_budget_is_not_over_budget() -> None:
    status = _status(maximum_visual_budget=100.0, total_estimated_cost=100.0)

    assert status.is_over_budget is False
