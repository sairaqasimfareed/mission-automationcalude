from __future__ import annotations

import pytest

from src.models.editorial_critique import (
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
)
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType
from src.services.llm.llm_service import LLMServiceResult
from src.services.script_revision_service import ScriptRevisionService
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


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=15,
                narrative_function=StoryBeatType.HOOK,
                narration="The crew vanished without a trace.",
                tension_level=60,
            ),
            ScriptSegment(
                segment_number=2,
                start_seconds=15,
                end_seconds=30,
                narrative_function=StoryBeatType.PAYOFF,
                narration="The crew vanished without a trace, again.",
                tension_level=80,
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _finding(**overrides: object) -> CriticFinding:
    base: dict[str, object] = dict(
        dimension="narrative_coherence",
        severity=FindingSeverity.MAJOR,
        segment_number=2,
        problem="Segment 2 repeats segment 1's sentence verbatim.",
        reason="Repetition this close together reads as an editing error.",
        recommended_correction="Rewrite segment 2 to add new information.",
    )
    base.update(overrides)
    return CriticFinding(**base)


def _critique(**overrides: object) -> EditorialCritique:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        dimension_scores={"narrative_coherence": 40},
        findings=[_finding()],
        prompt_version="editorial_critique_prompt_v1.0.0",
    )
    base.update(overrides)
    return EditorialCritique(**base)


_REVISED_RESPONSE = "\n---\n".join(
    [
        "SEGMENT: 1\nNARRATION: The crew vanished without a trace.",
        "SEGMENT: 2\nNARRATION: A waterspout scare best explains the mystery.",
    ]
)


def test_revise_replaces_narration_only_for_flagged_segments() -> None:
    stub = _StubLLMService(content=_REVISED_RESPONSE)

    service = ScriptRevisionService(llm_service=stub)  # type: ignore[arg-type]

    original = _script()
    revised = service.revise(script=original, critique=_critique())

    assert (
        revised.segments[1].narration == "A waterspout scare best explains the mystery."
    )


def test_revise_preserves_timing_and_structure() -> None:
    stub = _StubLLMService(content=_REVISED_RESPONSE)

    service = ScriptRevisionService(llm_service=stub)  # type: ignore[arg-type]

    original = _script()
    revised = service.revise(script=original, critique=_critique())

    assert revised.segments[1].start_seconds == original.segments[1].start_seconds
    assert revised.segments[1].end_seconds == original.segments[1].end_seconds
    assert (
        revised.segments[1].narrative_function
        == original.segments[1].narrative_function
    )
    assert revised.segments[1].tension_level == original.segments[1].tension_level
    assert revised.topic == original.topic


def test_revise_leaves_a_segment_unchanged_when_not_returned() -> None:
    content = "SEGMENT: 2\nNARRATION: A waterspout scare best explains the mystery."

    stub = _StubLLMService(content=content)

    service = ScriptRevisionService(llm_service=stub)  # type: ignore[arg-type]

    original = _script()
    revised = service.revise(script=original, critique=_critique())

    assert revised.segments[0].narration == original.segments[0].narration


def test_revise_includes_general_findings_in_the_prompt() -> None:
    stub = _StubLLMService(content=_REVISED_RESPONSE)

    service = ScriptRevisionService(llm_service=stub)  # type: ignore[arg-type]

    general_finding = _finding(
        segment_number=None,
        problem="The script never resolves the opened curiosity loop.",
        recommended_correction="Add a closing line addressing the crew's fate.",
    )

    service.revise(script=_script(), critique=_critique(findings=[general_finding]))

    assert stub.last_request is not None
    assert "curiosity loop" in stub.last_request.prompt


def test_revise_raises_when_critique_has_no_findings() -> None:
    stub = _StubLLMService(content=_REVISED_RESPONSE)

    service = ScriptRevisionService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least one critique finding"):
        service.revise(script=_script(), critique=_critique(findings=[]))


def test_revise_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = ScriptRevisionService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Script revision failed"):
        service.revise(script=_script(), critique=_critique())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_REVISED_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        ScriptRevisionService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_REVISED_RESPONSE)

    service = ScriptRevisionService(llm_service=probe)  # type: ignore[arg-type]

    service.revise(script=_script(), critique=_critique())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = ScriptRevisionService(llm_service=replay)  # type: ignore[arg-type]

    revised = replay_service.revise(script=_script(), critique=_critique())

    assert len(revised.segments) == 2
