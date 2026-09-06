from __future__ import annotations

import pytest

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_selection_edit import (
    SelectionEditOperation,
    SelectionEditRequest,
)
from src.models.story_blueprint import StoryBeatType
from src.models.writing_directives import (
    DirectiveSource,
    WritingDirective,
    WritingDirectiveSet,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.script_selection_edit_service import ScriptSelectionEditService
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


def _service(llm: object) -> ScriptSelectionEditService:
    # The stub above duck-types LLMService's public interface but does
    # not inherit from it - the same accepted pattern already used in
    # test_script_generation_service.py.
    return ScriptSelectionEditService(llm_service=llm)  # type: ignore[arg-type]


def _segment(
    *,
    number: int,
    start: float,
    end: float,
    narration: str,
    narrative_function: StoryBeatType = StoryBeatType.ESCALATION,
    source_claim_references: list[str] | None = None,
) -> ScriptSegment:
    return ScriptSegment(
        segment_number=number,
        start_seconds=start,
        end_seconds=end,
        narrative_function=narrative_function,
        narration=narration,
        tension_level=50,
        source_claim_references=source_claim_references or [],
    )


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=90,
        segments=[
            _segment(
                number=1,
                start=0,
                end=30,
                narration="The crew vanished without a trace.",
                narrative_function=StoryBeatType.HOOK,
            ),
            _segment(
                number=2,
                start=30,
                end=60,
                narration="Investigators searched for months.",
                source_claim_references=["fact-1"],
            ),
            _segment(
                number=3,
                start=60,
                end=90,
                narration="No answer was ever found.",
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def test_edit_replaces_only_the_target_segments_narration() -> None:
    llm = _StubLLMService(content="NARRATION: Investigators searched for years.")
    service = _service(llm)

    revised, _ = service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=2, operation=SelectionEditOperation.REWRITE
        ),
    )

    by_number = {segment.segment_number: segment for segment in revised.segments}
    assert by_number[2].narration == "Investigators searched for years."
    # Every other segment is byte-identical - hook preservation.
    assert by_number[1].narration == "The crew vanished without a trace."
    assert by_number[3].narration == "No answer was ever found."


def test_edit_preserves_timing_and_narrative_function() -> None:
    llm = _StubLLMService(content="NARRATION: New wording.")
    service = _service(llm)

    revised, _ = service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=1, operation=SelectionEditOperation.MORE_SUSPENSEFUL
        ),
    )

    edited = next(s for s in revised.segments if s.segment_number == 1)
    assert edited.start_seconds == 0
    assert edited.end_seconds == 30
    assert edited.narrative_function == StoryBeatType.HOOK


def test_edit_preserves_source_claim_references() -> None:
    llm = _StubLLMService(content="NARRATION: Investigators searched for years.")
    service = _service(llm)

    revised, _ = service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=2, operation=SelectionEditOperation.SHORTEN
        ),
    )

    edited = next(s for s in revised.segments if s.segment_number == 2)
    assert edited.source_claim_references == ["fact-1"]


def test_edit_with_a_selection_replaces_only_that_substring() -> None:
    llm = _StubLLMService(
        content="NARRATION: disappeared under mysterious circumstances"
    )
    service = _service(llm)

    revised, _ = service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=1,
            operation=SelectionEditOperation.REWRITE,
            selected_text="vanished without a trace",
        ),
    )

    edited = next(s for s in revised.segments if s.segment_number == 1)
    assert edited.narration == "The crew disappeared under mysterious circumstances."


def test_edit_rejects_a_selection_not_present_in_the_segment() -> None:
    service = _service(_StubLLMService(content="NARRATION: irrelevant"))

    with pytest.raises(ValueError, match="exact substring"):
        service.edit(
            script=_script(),
            request=SelectionEditRequest(
                segment_number=1,
                operation=SelectionEditOperation.REWRITE,
                selected_text="this text is not in the segment",
            ),
        )


def test_edit_rejects_an_unknown_segment_number() -> None:
    service = _service(_StubLLMService(content="NARRATION: irrelevant"))

    with pytest.raises(ValueError, match="no segment 99"):
        service.edit(
            script=_script(),
            request=SelectionEditRequest(
                segment_number=99, operation=SelectionEditOperation.REWRITE
            ),
        )


def test_context_envelope_includes_surrounding_segments_in_the_prompt() -> None:
    llm = _StubLLMService(content="NARRATION: New wording.")
    service = _service(llm)

    service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=2, operation=SelectionEditOperation.IMPROVE_TRANSITION
        ),
    )

    assert llm.last_request is not None
    prompt = llm.last_request.prompt
    assert "The crew vanished without a trace." in prompt
    assert "Investigators searched for months." in prompt
    assert "No answer was ever found." in prompt


def test_custom_instruction_reaches_the_prompt() -> None:
    llm = _StubLLMService(content="NARRATION: New wording.")
    service = _service(llm)

    service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=1,
            operation=SelectionEditOperation.CUSTOM,
            custom_instruction="Make it sound like a radio broadcast.",
        ),
    )

    assert llm.last_request is not None
    assert "Make it sound like a radio broadcast." in llm.last_request.prompt


def test_writing_directives_are_included_when_supplied() -> None:
    llm = _StubLLMService(content="NARRATION: New wording.")
    service = _service(llm)
    directives = WritingDirectiveSet(
        directives=[
            WritingDirective(
                text="Never reveal the ending early.",
                source=DirectiveSource.SYSTEM,
                overridable=False,
            )
        ],
        prompt_version="writing_directives_prompt_v1.0.0",
    )

    service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=1, operation=SelectionEditOperation.REWRITE
        ),
        writing_directives=directives,
    )

    assert llm.last_request is not None
    assert "Never reveal the ending early." in llm.last_request.prompt


def test_provider_failure_raises_a_runtime_error() -> None:
    service = _service(_StubLLMService(content="", success=False))

    with pytest.raises(RuntimeError, match="Script selection edit failed"):
        service.edit(
            script=_script(),
            request=SelectionEditRequest(
                segment_number=1, operation=SelectionEditOperation.REWRITE
            ),
        )


def test_negative_estimated_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ScriptSelectionEditService(
            llm_service=_StubLLMService(content="NARRATION: x"),  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_round_trip() -> None:
    class _DryRunLLMService:
        def generate(
            self,
            request: LLMRequest,
            *,
            estimated_cost_usd: float = 0.0,
            profile_ids: list[str] | None = None,
        ) -> LLMServiceResult:
            result = LLMCallResult(
                status=LLMCallStatus.SUCCESS,
                provider=LLMProvider.OPENAI,
                model="dry-run",
                content=request.dry_run_response,
            )

            return LLMServiceResult(result=result, selected_profile_id="dry-run")

    service = _service(_DryRunLLMService())

    revised, summary = service.edit(
        script=_script(),
        request=SelectionEditRequest(
            segment_number=1, operation=SelectionEditOperation.REWRITE
        ),
    )

    assert "Dry-run edited narration for segment 1" in (
        next(s for s in revised.segments if s.segment_number == 1).narration
    )
    assert "Segment 1" in summary
