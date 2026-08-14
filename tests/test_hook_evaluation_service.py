from __future__ import annotations

import pytest

from src.models.hook import HookCandidate
from src.models.research import ResearchResult, ResearchSource, ResearchStatus
from src.services.hook_evaluation_service import (
    HookEvaluationService,
    select_winning_hook,
)
from src.services.llm.llm_service import LLMServiceResult
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


def _research() -> ResearchResult:
    return ResearchResult(
        topic="The Mary Celeste",
        research_summary="An overview of the ship's disappearance.",
        key_facts=["The crew was never found."],
        interesting_angles=["The missing logbook."],
        potential_hooks=["What happened to the crew?"],
        risk_notes=["Claims should be verified."],
        sources=[ResearchSource(title="Test source", confidence_score=70)],
        fact_confidence_score=70,
        prompt_version="research_prompt_v2.0.0",
        status=ResearchStatus.APPROVED,
    )


def _hooks() -> list[HookCandidate]:
    return [
        HookCandidate(text="The crew vanished without a trace."),
        HookCandidate(text="You won't BELIEVE what happened next!!!"),
    ]


def _score_block(
    text: str,
    *,
    curiosity: int = 85,
    rejected: str = "no",
    reasons: str = "none",
) -> str:
    return (
        f"HOOK_TEXT: {text}\n"
        f"IMMEDIATE_CURIOSITY: {curiosity}\n"
        "SPECIFICITY: 80\n"
        "STAKES: 75\n"
        "CLARITY: 80\n"
        "EMOTIONAL_IMPACT: 70\n"
        "NOVELTY: 75\n"
        "RELEVANCE: 85\n"
        "AUDIENCE_FIT: 80\n"
        "FACTUAL_SUPPORT: 90\n"
        "SPOILER_RISK: 10\n"
        f"REJECTED: {rejected}\n"
        f"REJECTION_REASONS: {reasons}\n"
        "REASONING: Strong, specific hook grounded in verified facts."
    )


_TWO_EVALUATION_BLOCKS = "\n---\n".join(
    [
        _score_block("The crew vanished without a trace.", curiosity=90),
        _score_block(
            "You won't BELIEVE what happened next!!!",
            curiosity=60,
            rejected="yes",
            reasons="misleading_clickbait",
        ),
    ]
)


def test_evaluate_parses_and_matches_both_hooks_by_text() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste", hooks=_hooks(), research=_research()
    )

    assert len(evaluations) == 2
    texts = {evaluation.hook_text for evaluation in evaluations}
    assert texts == {
        "The crew vanished without a trace.",
        "You won't BELIEVE what happened next!!!",
    }


def test_evaluate_parses_rejection_reasons() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste", hooks=_hooks(), research=_research()
    )

    rejected = next(e for e in evaluations if e.rejected)

    assert rejected.hook_text == "You won't BELIEVE what happened next!!!"
    assert "misleading_clickbait" in [
        reason.value for reason in rejected.rejection_reasons
    ]


def test_evaluate_parses_multiple_rejection_reasons() -> None:
    content = _score_block(
        "The crew vanished without a trace.",
        rejected="yes",
        reasons="misleading_clickbait, complete_spoiler",
    )

    stub = _StubLLMService(content=content)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste",
        hooks=[HookCandidate(text="The crew vanished without a trace.")],
        research=_research(),
    )

    reason_values = {reason.value for reason in evaluations[0].rejection_reasons}
    assert reason_values == {"misleading_clickbait", "complete_spoiler"}


def test_evaluate_skips_a_block_whose_text_does_not_match_any_hook() -> None:
    content = "\n---\n".join(
        [
            _score_block("An unrelated hook text."),
            _score_block("The crew vanished without a trace."),
        ]
    )

    stub = _StubLLMService(content=content)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste", hooks=_hooks(), research=_research()
    )

    assert len(evaluations) == 1
    assert evaluations[0].hook_text == "The crew vanished without a trace."


def test_evaluate_only_makes_one_llm_call_for_all_hooks() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    service.evaluate(topic="The Mary Celeste", hooks=_hooks(), research=_research())

    assert stub.last_request is not None
    assert "The crew vanished without a trace." in stub.last_request.prompt
    assert "You won't BELIEVE what happened next!!!" in stub.last_request.prompt


def test_evaluate_raises_on_empty_hook_list() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="At least one hook candidate"):
        service.evaluate(topic="The Mary Celeste", hooks=[], research=_research())


def test_evaluate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Hook evaluation failed"):
        service.evaluate(topic="The Mary Celeste", hooks=_hooks(), research=_research())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    with pytest.raises(ValueError, match="cannot be negative"):
        HookEvaluationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = HookEvaluationService(llm_service=probe)  # type: ignore[arg-type]

    service.evaluate(topic="The Mary Celeste", hooks=_hooks(), research=_research())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = HookEvaluationService(llm_service=replay)  # type: ignore[arg-type]

    evaluations = replay_service.evaluate(
        topic="The Mary Celeste", hooks=_hooks(), research=_research()
    )

    assert len(evaluations) == 2


def test_select_winning_hook_excludes_rejected_candidates() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste", hooks=_hooks(), research=_research()
    )

    winner = select_winning_hook(evaluations)

    assert winner.hook_text == "The crew vanished without a trace."
    assert winner.rejected is False


def test_select_winning_hook_raises_when_all_rejected() -> None:
    all_rejected = "\n---\n".join(
        [
            _score_block(
                "The crew vanished without a trace.",
                rejected="yes",
                reasons="unsupported_claim",
            ),
        ]
    )

    stub = _StubLLMService(content=all_rejected)

    service = HookEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste",
        hooks=[HookCandidate(text="The crew vanished without a trace.")],
        research=_research(),
    )

    with pytest.raises(ValueError, match="every candidate was rejected"):
        select_winning_hook(evaluations)


def test_select_winning_hook_raises_on_empty_list() -> None:
    with pytest.raises(ValueError, match="No eligible hook evaluations"):
        select_winning_hook([])
