from __future__ import annotations

import pytest

from src.models.scene import Scene
from src.models.visual_continuity import (
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.shot_planning_service import ShotPlanningService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        status = (
            LLMCallStatus.SUCCESS if self._success else LLMCallStatus.PROVIDER_ERROR
        )
        result = LLMCallResult(
            status=status,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=self._content if self._success else None,
            error_message=None if self._success else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="openai-main" if self._success else None,
            all_providers_failed=not self._success,
        )


def _scene(number: int, duration: int = 8) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="The captain surveys the horizon.",
        visual_prompt="A ship at sea.",
        estimated_duration_seconds=duration,
    )


def _bible() -> VisualContinuityBible:
    return VisualContinuityBible(
        script_lock_hash="hash123",
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="The captain surveys.",
                outgoing_state=VisualState(wardrobe="Uniform"),
            )
        ],
    )


_VALID_RESPONSE = (
    "SCENE: 1\n"
    "SHOT_SIZE: medium\n"
    "SHOT_ANGLE: eye_level\n"
    "MOVEMENT: static\n"
    "LENS: 35mm\n"
    "COMPOSITION: Rule of thirds.\n"
    "BLOCKING: Center frame.\n"
    "LIGHTING: Soft morning light.\n"
    "ACTION: The captain surveys the horizon.\n"
    "TRANSITION_IN: cut\n"
    "TRANSITION_OUT: cut\n"
    "BEATS: 0-2s: establish; 2-8s: action"
)


def test_plan_creates_one_shot_per_scene() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = ShotPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan(
        scenes=[_scene(1)],
        visual_continuity_bible=_bible(),
        script_lock_hash="hash123",
        topic="The Mary Celeste",
    )

    assert plan.has_exactly_one_shot_per_scene is True
    assert len(plan.shots) == 1


def test_plan_uses_scene_duration_not_llm_duration() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = ShotPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan(
        scenes=[_scene(1, duration=12)],
        visual_continuity_bible=_bible(),
        script_lock_hash="hash123",
        topic="The Mary Celeste",
    )

    shot = plan.shot_for_scene(1)
    assert shot is not None
    assert shot.duration_seconds == 12.0


def test_plan_parses_temporal_action_beats() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = ShotPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan(
        scenes=[_scene(1)],
        visual_continuity_bible=_bible(),
        script_lock_hash="hash123",
        topic="The Mary Celeste",
    )

    shot = plan.shot_for_scene(1)
    assert shot is not None
    assert len(shot.temporal_action_beats) == 2


def test_plan_fills_a_fallback_shot_for_a_scene_the_llm_skipped() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)  # only covers scene 1
    service = ShotPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan(
        scenes=[_scene(1), _scene(2)],
        visual_continuity_bible=_bible(),
        script_lock_hash="hash123",
        topic="The Mary Celeste",
    )

    assert plan.has_exactly_one_shot_per_scene is True
    assert plan.shot_for_scene(2) is not None


def test_plan_requires_at_least_one_scene() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = ShotPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least one scene"):
        service.plan(
            scenes=[],
            visual_continuity_bible=_bible(),
            script_lock_hash="hash123",
            topic="The Mary Celeste",
        )


def test_plan_raises_on_provider_failure() -> None:
    stub = _StubLLMService(content="", success=False)
    service = ShotPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Shot planning failed"):
        service.plan(
            scenes=[_scene(1)],
            visual_continuity_bible=_bible(),
            script_lock_hash="hash123",
            topic="The Mary Celeste",
        )
