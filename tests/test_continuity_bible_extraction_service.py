from __future__ import annotations

import pytest

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType
from src.services.continuity_bible_extraction_service import (
    ContinuityBibleExtractionService,
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
                narration="Captain Briggs commanded the Mary Celeste.",
                tension_level=60,
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


_VALID_RESPONSE = "\n---\n".join(
    [
        (
            "TYPE: character\n"
            "NAME: Captain Briggs\n"
            "DESCRIPTION: Captain of the Mary Celeste.\n"
            "SEGMENT: 1"
        ),
        (
            "TYPE: location\n"
            "NAME: The Mary Celeste\n"
            "DESCRIPTION: A brigantine ship.\n"
            "SEGMENT: 1"
        ),
    ]
)


def test_extract_parses_multiple_entry_types() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)

    service = ContinuityBibleExtractionService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.extract(_script())

    assert len(bible.entries) == 2
    assert len(bible.characters) == 1
    assert len(bible.locations) == 1
    assert bible.characters[0].name == "Captain Briggs"


def test_extract_skips_a_block_with_an_invalid_type() -> None:
    content = (
        "TYPE: not_a_real_type\n"
        "NAME: Something\n"
        "DESCRIPTION: A description.\n"
        "SEGMENT: 1"
    )

    stub = _StubLLMService(content=content)

    service = ContinuityBibleExtractionService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.extract(_script())

    assert bible.entries == []


def test_extract_skips_a_block_with_a_non_integer_segment() -> None:
    content = (
        "TYPE: character\n"
        "NAME: Captain Briggs\n"
        "DESCRIPTION: Captain of the Mary Celeste.\n"
        "SEGMENT: unknown"
    )

    stub = _StubLLMService(content=content)

    service = ContinuityBibleExtractionService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.extract(_script())

    assert bible.entries == []


def test_extract_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = ContinuityBibleExtractionService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Continuity bible extraction failed"):
        service.extract(_script())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        ContinuityBibleExtractionService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_VALID_RESPONSE)

    service = ContinuityBibleExtractionService(llm_service=probe)  # type: ignore[arg-type]

    service.extract(_script())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = ContinuityBibleExtractionService(llm_service=replay)  # type: ignore[arg-type]

    bible = replay_service.extract(_script())

    assert len(bible.entries) > 0
