from __future__ import annotations

import pytest

from src.models.cinematic_prompt import (
    QUALITY_BLOCK_THRESHOLD,
    CinematicPromptPackage,
    ResolvedCinematicPrompt,
)


def _prompt(scene_number: int, **overrides: object) -> ResolvedCinematicPrompt:
    base: dict[str, object] = dict(
        scene_number=scene_number,
        script_lock_hash="hash123",
        prompt_text="A ship's captain surveys the horizon at dawn.",
    )
    base.update(overrides)
    return ResolvedCinematicPrompt(**base)


def test_rejects_blank_prompt_text() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        _prompt(1, prompt_text="   ")


def test_unscored_prompt_is_not_scored_and_not_blocked() -> None:
    prompt = _prompt(1)

    assert prompt.is_scored is False
    assert prompt.lowest_score is None
    assert prompt.is_blocked is False


def test_scored_prompt_above_threshold_is_not_blocked() -> None:
    prompt = _prompt(
        1,
        specificity_score=80,
        continuity_score=80,
        action_score=80,
        camera_score=80,
        lighting_score=80,
        reveal_safety_score=80,
    )

    assert prompt.is_scored is True
    assert prompt.is_blocked is False


def test_scored_prompt_below_threshold_is_blocked() -> None:
    prompt = _prompt(
        1,
        specificity_score=80,
        continuity_score=QUALITY_BLOCK_THRESHOLD - 1,
        action_score=80,
        camera_score=80,
        lighting_score=80,
        reveal_safety_score=80,
    )

    assert prompt.is_blocked is True
    assert prompt.lowest_score == QUALITY_BLOCK_THRESHOLD - 1


def test_prompt_for_scene_finds_by_scene_number() -> None:
    prompt = _prompt(2)
    package = CinematicPromptPackage(script_lock_hash="hash123", prompts=[prompt])

    assert package.prompt_for_scene(2) is prompt
    assert package.prompt_for_scene(99) is None


def test_package_is_ready_only_when_every_prompt_scored_and_unblocked() -> None:
    fully_scored = _prompt(
        1,
        specificity_score=80,
        continuity_score=80,
        action_score=80,
        camera_score=80,
        lighting_score=80,
        reveal_safety_score=80,
    )
    package = CinematicPromptPackage(script_lock_hash="hash123", prompts=[fully_scored])

    assert package.is_ready is True


def test_package_is_not_ready_when_a_prompt_is_unscored() -> None:
    package = CinematicPromptPackage(script_lock_hash="hash123", prompts=[_prompt(1)])

    assert package.is_ready is False


def test_empty_package_is_not_ready() -> None:
    package = CinematicPromptPackage(script_lock_hash="hash123")

    assert package.is_ready is False


def test_blocked_prompts_lists_only_blocked_ones() -> None:
    blocked = _prompt(
        1,
        specificity_score=10,
        continuity_score=80,
        action_score=80,
        camera_score=80,
        lighting_score=80,
        reveal_safety_score=80,
    )
    healthy = _prompt(
        2,
        specificity_score=80,
        continuity_score=80,
        action_score=80,
        camera_score=80,
        lighting_score=80,
        reveal_safety_score=80,
    )
    package = CinematicPromptPackage(
        script_lock_hash="hash123", prompts=[blocked, healthy]
    )

    assert package.blocked_prompts == [blocked]
