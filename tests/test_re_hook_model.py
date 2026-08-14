from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.re_hook import ReHook, ReHookPlan, ReHookType


def _re_hook(**overrides: object) -> ReHook:
    base: dict[str, object] = dict(
        position_seconds=30.0,
        re_hook_type=ReHookType.NEW_QUESTION,
        text="But the logbook raised a bigger question.",
    )
    base.update(overrides)
    return ReHook(**base)


def test_valid_re_hook_constructs() -> None:
    re_hook = _re_hook()

    assert re_hook.re_hook_type == ReHookType.NEW_QUESTION


def test_re_hook_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        _re_hook(text="   ")


def test_plan_requires_at_least_one_re_hook() -> None:
    with pytest.raises(ValidationError):
        ReHookPlan(topic="The Mary Celeste", re_hooks=[], prompt_version="v1")


def test_repetitive_phrasing_empty_when_all_distinct() -> None:
    plan = ReHookPlan(
        topic="The Mary Celeste",
        re_hooks=[
            _re_hook(
                position_seconds=30, text="But the logbook raised a bigger question."
            ),
            _re_hook(
                position_seconds=55, text="Then investigators found something else."
            ),
        ],
        prompt_version="v1",
    )

    assert plan.repetitive_phrasing == []


def test_repetitive_phrasing_detects_exact_duplicates_case_insensitively() -> None:
    plan = ReHookPlan(
        topic="The Mary Celeste",
        re_hooks=[
            _re_hook(position_seconds=30, text="But that's not the scary part."),
            _re_hook(position_seconds=55, text="  BUT THAT'S NOT THE SCARY PART.  "),
        ],
        prompt_version="v1",
    )

    assert len(plan.repetitive_phrasing) == 1
