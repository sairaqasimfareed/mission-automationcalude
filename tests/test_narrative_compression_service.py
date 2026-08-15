from __future__ import annotations

import pytest

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType
from src.services.llm.llm_service import LLMServiceResult
from src.services.narrative_compression_service import NarrativeCompressionService
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
                end_seconds=7,
                narrative_function=StoryBeatType.HOOK,
                narration=(
                    "In this video, we are going to be talking about "
                    "the crew, who, as you might expect, vanished "
                    "without a trace, which is very mysterious."
                ),
                tension_level=60,
            ),
            ScriptSegment(
                segment_number=2,
                start_seconds=7,
                end_seconds=30,
                narrative_function=StoryBeatType.PAYOFF,
                narration="The most likely theory is a waterspout scare.",
                tension_level=80,
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


_COMPRESSED_RESPONSE = "\n---\n".join(
    [
        "SEGMENT: 1\nNARRATION: The crew vanished without a trace.",
        "SEGMENT: 2\nNARRATION: The most likely theory is a waterspout scare.",
    ]
)


def test_compress_replaces_narration_only() -> None:
    stub = _StubLLMService(content=_COMPRESSED_RESPONSE)

    service = NarrativeCompressionService(llm_service=stub)  # type: ignore[arg-type]

    original = _script()
    compressed = service.compress(original)

    assert compressed.segments[0].narration == "The crew vanished without a trace."
    assert len(compressed.segments[0].narration) < len(original.segments[0].narration)


def test_compress_preserves_timing_and_structure() -> None:
    stub = _StubLLMService(content=_COMPRESSED_RESPONSE)

    service = NarrativeCompressionService(llm_service=stub)  # type: ignore[arg-type]

    original = _script()
    compressed = service.compress(original)

    assert compressed.segments[0].start_seconds == original.segments[0].start_seconds
    assert compressed.segments[0].end_seconds == original.segments[0].end_seconds
    assert (
        compressed.segments[0].narrative_function
        == original.segments[0].narrative_function
    )
    assert compressed.segments[0].tension_level == original.segments[0].tension_level
    assert compressed.topic == original.topic
    assert compressed.target_duration_seconds == original.target_duration_seconds


def test_compress_leaves_a_segment_unchanged_when_not_returned() -> None:
    content = "SEGMENT: 1\nNARRATION: The crew vanished without a trace."

    stub = _StubLLMService(content=content)

    service = NarrativeCompressionService(llm_service=stub)  # type: ignore[arg-type]

    original = _script()
    compressed = service.compress(original)

    assert compressed.segments[1].narration == original.segments[1].narration


def test_compress_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = NarrativeCompressionService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Narrative compression failed"):
        service.compress(_script())


def test_compress_raises_on_empty_content() -> None:
    stub = _StubLLMService(content="   ")

    service = NarrativeCompressionService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty content"):
        service.compress(_script())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_COMPRESSED_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        NarrativeCompressionService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_COMPRESSED_RESPONSE)

    service = NarrativeCompressionService(llm_service=probe)  # type: ignore[arg-type]

    service.compress(_script())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = NarrativeCompressionService(llm_service=replay)  # type: ignore[arg-type]

    compressed = replay_service.compress(_script())

    assert len(compressed.segments) == 2
