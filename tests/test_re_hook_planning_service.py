from __future__ import annotations

import pytest

from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint
from src.services.llm.llm_service import LLMServiceResult
from src.services.re_hook_planning_service import ReHookPlanningService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success
        self.last_request: LLMRequest | None = None

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.last_request = request

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


def _angle() -> StoryAngle:
    return StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the ship's missing final log entry.",
    )


def _blueprint_with_re_hooks() -> StoryBlueprint:
    return StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=60,
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=7,
                purpose="Open cold.",
                tension_level=60,
            ),
            StoryBeat(
                beat_type=StoryBeatType.RE_HOOK,
                start_seconds=30,
                end_seconds=32,
                purpose="Re-establish curiosity.",
                tension_level=50,
            ),
            StoryBeat(
                beat_type=StoryBeatType.RE_HOOK,
                start_seconds=55,
                end_seconds=57,
                purpose="Re-establish curiosity again.",
                tension_level=70,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )


def _blueprint_without_re_hooks() -> StoryBlueprint:
    return StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=10,
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=10,
                purpose="Open cold.",
                tension_level=60,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )


_TWO_RE_HOOK_BLOCKS = "\n---\n".join(
    [
        "POSITION: 30\nTYPE: new_question\nTEXT: But the logbook raised a bigger question.",
        "POSITION: 55\nTYPE: increased_stakes\nTEXT: Then investigators found something else.",
    ]
)


def test_plan_parses_re_hooks_matching_blueprint_positions() -> None:
    stub = _StubLLMService(content=_TWO_RE_HOOK_BLOCKS)

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan(
        topic="The Mary Celeste",
        blueprint=_blueprint_with_re_hooks(),
        story_angle=_angle(),
    )

    assert len(plan.re_hooks) == 2
    assert plan.re_hooks[0].position_seconds == 30.0
    assert plan.re_hooks[1].position_seconds == 55.0


def test_plan_raises_when_blueprint_has_no_re_hook_beats() -> None:
    stub = _StubLLMService(content=_TWO_RE_HOOK_BLOCKS)

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="no RE_HOOK beats"):
        service.plan(
            topic="The Mary Celeste",
            blueprint=_blueprint_without_re_hooks(),
            story_angle=_angle(),
        )


def test_plan_includes_re_hook_positions_in_prompt() -> None:
    stub = _StubLLMService(content=_TWO_RE_HOOK_BLOCKS)

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    service.plan(
        topic="The Mary Celeste",
        blueprint=_blueprint_with_re_hooks(),
        story_angle=_angle(),
    )

    assert stub.last_request is not None
    assert "30.0s" in stub.last_request.prompt
    assert "55.0s" in stub.last_request.prompt


def test_plan_skips_a_block_with_an_unrecognized_type() -> None:
    content = "\n---\n".join(
        [
            "POSITION: 30\nTYPE: not_a_real_type\nTEXT: Should be skipped.",
            "POSITION: 55\nTYPE: new_threat\nTEXT: A real re-hook.",
        ]
    )

    stub = _StubLLMService(content=content)

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan(
        topic="The Mary Celeste",
        blueprint=_blueprint_with_re_hooks(),
        story_angle=_angle(),
    )

    assert len(plan.re_hooks) == 1
    assert plan.re_hooks[0].text == "A real re-hook."


def test_plan_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Re-hook planning failed"):
        service.plan(
            topic="The Mary Celeste",
            blueprint=_blueprint_with_re_hooks(),
            story_angle=_angle(),
        )


def test_plan_raises_when_no_re_hooks_parsed() -> None:
    stub = _StubLLMService(content="This response has no valid blocks at all.")

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable re-hooks"):
        service.plan(
            topic="The Mary Celeste",
            blueprint=_blueprint_with_re_hooks(),
            story_angle=_angle(),
        )


def test_plan_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_TWO_RE_HOOK_BLOCKS)

    service = ReHookPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.plan(
            topic="   ",
            blueprint=_blueprint_with_re_hooks(),
            story_angle=_angle(),
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_RE_HOOK_BLOCKS)

    with pytest.raises(ValueError, match="cannot be negative"):
        ReHookPlanningService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_RE_HOOK_BLOCKS)

    service = ReHookPlanningService(llm_service=probe)  # type: ignore[arg-type]

    service.plan(
        topic="The Mary Celeste",
        blueprint=_blueprint_with_re_hooks(),
        story_angle=_angle(),
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = ReHookPlanningService(llm_service=replay)  # type: ignore[arg-type]

    plan = replay_service.plan(
        topic="The Mary Celeste",
        blueprint=_blueprint_with_re_hooks(),
        story_angle=_angle(),
    )

    assert len(plan.re_hooks) == 2
