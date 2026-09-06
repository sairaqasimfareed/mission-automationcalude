from __future__ import annotations

import pytest

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityEntryType,
)
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.production_ambiguity import (
    AmbiguityResolutionStatus,
    ProductionAmbiguity,
)
from src.models.story_blueprint import StoryBeatType
from src.services.llm.llm_service import LLMServiceResult
from src.services.production_ambiguity_service import ProductionAmbiguityService
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


def _service(llm: object) -> ProductionAmbiguityService:
    return ProductionAmbiguityService(llm_service=llm)  # type: ignore[arg-type]


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=30,
                narrative_function=StoryBeatType.HOOK,
                narration="The crew vanished without a trace.",
                tension_level=60,
            )
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def test_detect_parses_multiple_ambiguities() -> None:
    content = (
        "DESCRIPTION: The exact time period is not stated.\n"
        "SEGMENT_NUMBER: none\n"
        "CONTINUITY_CRITICAL: no\n"
        "---\n"
        "DESCRIPTION: The captain's fate is left unclear.\n"
        "SEGMENT_NUMBER: 1\n"
        "CONTINUITY_CRITICAL: yes"
    )
    service = _service(_StubLLMService(content=content))

    ambiguities = service.detect(script=_script(), continuity_bible=None)

    assert len(ambiguities) == 2
    assert ambiguities[0].continuity_critical is False
    assert ambiguities[1].continuity_critical is True
    assert ambiguities[1].segment_number == 1


def test_detect_with_no_ambiguities_returns_empty_list() -> None:
    service = _service(_StubLLMService(content=""))

    ambiguities = service.detect(script=_script(), continuity_bible=None)

    assert ambiguities == []


def test_detect_includes_continuity_bible_entries_in_the_prompt() -> None:
    llm = _StubLLMService(content="")
    service = _service(llm)
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            ContinuityEntry(
                entry_type=ContinuityEntryType.CHARACTER,
                name="Captain Briggs",
                description="The ship's captain.",
                first_mentioned_segment=1,
            )
        ],
        prompt_version="continuity_bible_prompt_v1.0.0",
    )

    service.detect(script=_script(), continuity_bible=bible)

    assert llm.last_request is not None
    assert "Captain Briggs" in llm.last_request.prompt


def test_detect_provider_failure_raises() -> None:
    service = _service(_StubLLMService(content="", success=False))

    with pytest.raises(RuntimeError, match="Production ambiguity detection failed"):
        service.detect(script=_script(), continuity_bible=None)


def test_resolve_manually_sets_status_and_note() -> None:
    service = _service(_StubLLMService(content=""))
    ambiguity = ProductionAmbiguity(description="Unclear setting.")

    resolved = service.resolve_manually(ambiguity=ambiguity, note="Set in 1872.")

    assert resolved.status == AmbiguityResolutionStatus.RESOLVED_MANUALLY
    assert resolved.resolution_note == "Set in 1872."


def test_resolve_manually_rejects_a_blank_note() -> None:
    service = _service(_StubLLMService(content=""))
    ambiguity = ProductionAmbiguity(description="Unclear setting.")

    with pytest.raises(ValueError, match="requires a note"):
        service.resolve_manually(ambiguity=ambiguity, note="   ")


def test_resolve_manually_rejects_an_already_resolved_ambiguity() -> None:
    service = _service(_StubLLMService(content=""))
    ambiguity = ProductionAmbiguity(
        description="Unclear setting.",
        status=AmbiguityResolutionStatus.RESOLVED_MANUALLY,
        resolution_note="Already resolved.",
    )

    with pytest.raises(ValueError, match="already resolved"):
        service.resolve_manually(ambiguity=ambiguity, note="Another note.")


def test_resolve_by_ai_sets_status_and_note() -> None:
    service = _service(
        _StubLLMService(content="DECISION: Assume a contemporary setting.")
    )
    ambiguity = ProductionAmbiguity(description="Unclear setting.")

    resolved = service.resolve_by_ai(ambiguity=ambiguity, script=_script())

    assert resolved.status == AmbiguityResolutionStatus.RESOLVED_BY_AI
    assert resolved.resolution_note == "Assume a contemporary setting."


def test_resolve_by_ai_rejects_an_already_resolved_ambiguity() -> None:
    service = _service(_StubLLMService(content="DECISION: x"))
    ambiguity = ProductionAmbiguity(
        description="Unclear setting.",
        status=AmbiguityResolutionStatus.RESOLVED_BY_AI,
        resolution_note="Already resolved.",
    )

    with pytest.raises(ValueError, match="already resolved"):
        service.resolve_by_ai(ambiguity=ambiguity, script=_script())


def test_resolve_by_ai_provider_failure_raises() -> None:
    service = _service(_StubLLMService(content="", success=False))
    ambiguity = ProductionAmbiguity(description="Unclear setting.")

    with pytest.raises(RuntimeError, match="Production ambiguity resolution failed"):
        service.resolve_by_ai(ambiguity=ambiguity, script=_script())


def test_negative_estimated_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ProductionAmbiguityService(
            llm_service=_StubLLMService(content=""),  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content="")
    service = _service(probe)

    service.detect(script=_script(), continuity_bible=None)

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = _service(replay)

    ambiguities = replay_service.detect(script=_script(), continuity_bible=None)

    assert len(ambiguities) == 1
