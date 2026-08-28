from __future__ import annotations

import pytest

from src.models.research import ResearchSource, SourceStatus
from src.services.fact_check_service import FactCheckService
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


def _sources() -> list[ResearchSource]:
    return [
        ResearchSource(title="Primary account", url="https://example.com/a"),
        ResearchSource(
            title="Rejected forum post",
            url="https://example.com/b",
            status=SourceStatus.REJECTED,
        ),
    ]


def test_check_parses_a_supported_claim() -> None:
    content = (
        "IS_SUPPORTED: yes\n"
        "CONFIDENCE: 85\n"
        "MATCHED_SOURCES: 1\n"
        "REASONING: The primary account directly confirms this claim."
    )
    stub = _StubLLMService(content=content)

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]
    sources = _sources()

    result = service.check(claim_text="The ship was found seaworthy.", sources=sources)

    assert result.is_supported is True
    assert result.confidence == 85
    assert result.matched_source_ids == [sources[0].id]


def test_check_excludes_rejected_sources_from_the_prompt() -> None:
    stub = _StubLLMService(
        content=(
            "IS_SUPPORTED: no\nCONFIDENCE: 20\nMATCHED_SOURCES: none\n"
            "REASONING: No accepted source supports this."
        )
    )

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]
    service.check(claim_text="A claim.", sources=_sources())

    assert stub.last_request is not None
    assert "Rejected forum post" not in stub.last_request.prompt
    assert "Primary account" in stub.last_request.prompt


def test_check_parses_an_unsupported_claim_with_no_matched_sources() -> None:
    content = (
        "IS_SUPPORTED: no\n"
        "CONFIDENCE: 15\n"
        "MATCHED_SOURCES: none\n"
        "REASONING: No supplied source mentions this claim."
    )
    stub = _StubLLMService(content=content)

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]

    result = service.check(claim_text="An unsupported claim.", sources=_sources())

    assert result.is_supported is False
    assert result.matched_source_ids == []


def test_check_clamps_out_of_range_confidence() -> None:
    content = (
        "IS_SUPPORTED: yes\nCONFIDENCE: 500\nMATCHED_SOURCES: 1\n"
        "REASONING: Overconfident response."
    )
    stub = _StubLLMService(content=content)

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]

    result = service.check(claim_text="A claim.", sources=_sources())

    assert result.confidence == 100


def test_check_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Fact check failed"):
        service.check(claim_text="A claim.", sources=_sources())


def test_check_raises_when_response_is_unparseable() -> None:
    stub = _StubLLMService(content="This response has no labeled fields at all.")

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="unusable response"):
        service.check(claim_text="A claim.", sources=_sources())


def test_check_rejects_empty_claim_text() -> None:
    stub = _StubLLMService(content="IS_SUPPORTED: yes\nREASONING: n/a")

    service = FactCheckService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.check(claim_text="   ", sources=_sources())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content="IS_SUPPORTED: yes\nREASONING: n/a")

    with pytest.raises(ValueError, match="cannot be negative"):
        FactCheckService(llm_service=stub, estimated_cost_usd=-1.0)  # type: ignore[arg-type]


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content="IS_SUPPORTED: yes\nREASONING: n/a")

    service = FactCheckService(llm_service=probe)  # type: ignore[arg-type]
    service.check(claim_text="A claim.", sources=_sources())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = FactCheckService(llm_service=replay)  # type: ignore[arg-type]

    result = replay_service.check(claim_text="A claim.", sources=_sources())

    assert result.is_supported is True
