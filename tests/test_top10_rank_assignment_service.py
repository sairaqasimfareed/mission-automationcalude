from __future__ import annotations

import pytest

from src.models.scene import Scene
from src.services.llm.llm_service import LLMServiceResult
from src.services.top10_rank_assignment_service import TopTenRankAssignmentService
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


def _scenes() -> list[Scene]:
    return [
        Scene(
            scene_number=1,
            title="Intro",
            narration="Today we're counting down the ten most terrifying survival stories.",
            visual_prompt="A dramatic wide shot of a wilderness.",
            estimated_duration_seconds=6,
        ),
        Scene(
            scene_number=2,
            title="Number ten setup",
            narration="At number ten, a hiker got lost for three days in freezing rain.",
            visual_prompt="A hiker walking through fog.",
            estimated_duration_seconds=8,
        ),
        Scene(
            scene_number=3,
            title="Number ten payoff",
            narration="He survived by building a shelter from fallen branches.",
            visual_prompt="A makeshift shelter in the woods.",
            estimated_duration_seconds=8,
        ),
        Scene(
            scene_number=4,
            title="Number nine",
            narration="At number nine, a sailor spent two weeks adrift after a storm.",
            visual_prompt="A small boat adrift at sea.",
            estimated_duration_seconds=8,
        ),
    ]


_TWO_RANK_RESPONSE = "\n---\n".join(
    [
        "RANK: 10\n"
        "SCENES: 2,3\n"
        "RATIONALE: Narration describes the hiker lost for three days, "
        "spanning two scenes (setup and payoff).",
        "RANK: 9\n"
        "SCENES: 4\n"
        "RATIONALE: Narration explicitly says 'At number nine'.",
    ]
)


def test_assign_groups_multi_scene_item_under_one_rank() -> None:
    stub = _StubLLMService(content=_TWO_RANK_RESPONSE)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    assert len(result.assignments) == 2

    rank_ten = next(a for a in result.assignments if a.rank == 10)
    assert rank_ten.scene_numbers == [2, 3]

    rank_nine = next(a for a in result.assignments if a.rank == 9)
    assert rank_nine.scene_numbers == [4]


def test_assign_leaves_hook_scene_unranked() -> None:
    stub = _StubLLMService(content=_TWO_RANK_RESPONSE)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    mapping = result.rank_by_scene_number()

    assert 1 not in mapping
    assert mapping[2] == 10
    assert mapping[3] == 10
    assert mapping[4] == 9


def test_missing_ranks_reports_every_unassigned_rank() -> None:
    stub = _StubLLMService(content=_TWO_RANK_RESPONSE)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    assert result.missing_ranks == [1, 2, 3, 4, 5, 6, 7, 8]


def test_missing_ranks_empty_when_all_ten_present() -> None:
    response = "\n---\n".join(
        f"RANK: {rank}\nSCENES: {rank}\nRATIONALE: Test rank {rank}."
        for rank in range(1, 11)
    )

    scenes = [
        Scene(
            scene_number=number,
            title=f"Scene {number}",
            narration=f"Narration for scene {number}.",
            visual_prompt="A visual.",
            estimated_duration_seconds=8,
        )
        for number in range(1, 11)
    ]

    stub = _StubLLMService(content=response)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=scenes)

    assert result.missing_ranks == []


def test_assign_skips_duplicate_rank_block() -> None:
    response = "\n---\n".join(
        [
            "RANK: 10\nSCENES: 2\nRATIONALE: First rank 10 block.",
            "RANK: 10\nSCENES: 3\nRATIONALE: Duplicate rank 10 block.",
        ]
    )

    stub = _StubLLMService(content=response)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    assert len(result.assignments) == 1
    assert result.assignments[0].scene_numbers == [2]
    assert any("duplicate" in warning.lower() for warning in result.warnings)


def test_assign_skips_scene_already_claimed_by_another_rank() -> None:
    response = "\n---\n".join(
        [
            "RANK: 10\nSCENES: 2\nRATIONALE: Scene 2 belongs to rank 10.",
            "RANK: 9\nSCENES: 2,4\nRATIONALE: Incorrectly reuses scene 2.",
        ]
    )

    stub = _StubLLMService(content=response)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    rank_nine = next(a for a in result.assignments if a.rank == 9)
    assert rank_nine.scene_numbers == [4]
    assert any("already assigned" in warning for warning in result.warnings)


def test_assign_skips_out_of_range_rank() -> None:
    response = "RANK: 11\nSCENES: 2\nRATIONALE: Invalid rank."

    stub = _StubLLMService(content=response)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    assert result.assignments == []
    assert any("out-of-range" in warning for warning in result.warnings)


def test_assign_skips_reference_to_unknown_scene() -> None:
    response = (
        "RANK: 10\nSCENES: 99\nRATIONALE: References a scene that does not exist."
    )

    stub = _StubLLMService(content=response)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    result = service.assign(scenes=_scenes())

    assert result.assignments == []
    assert any("unknown scene" in warning for warning in result.warnings)


def test_assign_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Rank assignment failed"):
        service.assign(scenes=_scenes())


def test_assign_rejects_empty_scene_list() -> None:
    stub = _StubLLMService(content=_TWO_RANK_RESPONSE)

    service = TopTenRankAssignmentService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least one scene"):
        service.assign(scenes=[])


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_RANK_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        TopTenRankAssignmentService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_RANK_RESPONSE)

    service = TopTenRankAssignmentService(llm_service=probe)  # type: ignore[arg-type]

    service.assign(scenes=_scenes())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = TopTenRankAssignmentService(llm_service=replay)  # type: ignore[arg-type]

    result = replay_service.assign(scenes=_scenes())

    assert len(result.assignments) == 2
