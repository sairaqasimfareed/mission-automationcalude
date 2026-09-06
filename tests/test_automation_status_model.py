from __future__ import annotations

from src.models.automation_status import AutomationStatus


def test_is_paused_true_when_a_decision_point_is_pending() -> None:
    status = AutomationStatus(pending_decision_point="story_angle")

    assert status.is_paused is True


def test_is_paused_false_with_no_pending_decision() -> None:
    status = AutomationStatus()

    assert status.is_paused is False


def test_is_complete_true_when_scene_planning_done_and_not_paused() -> None:
    status = AutomationStatus(completed_stages=["script", "scene_planning"])

    assert status.is_complete is True


def test_is_complete_false_without_scene_planning() -> None:
    status = AutomationStatus(completed_stages=["script"])

    assert status.is_complete is False


def test_is_complete_false_while_paused_even_with_scene_planning() -> None:
    status = AutomationStatus(
        completed_stages=["scene_planning"], pending_decision_point="final_script"
    )

    assert status.is_complete is False
