from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.services.llm.llm_service import LLMServiceResult
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_title_generation_service import (
    SEOTitleGenerationService,
)
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


def _context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Deep sea creatures",
        niche="ocean-life",
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        target_country="United States",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="Deep Sea Creatures Explained",
        script_content="Full script content about deep sea creatures.",
        research_summary="An overview of deep sea creatures.",
        key_facts=["Fact one.", "Fact two."],
        scene_count=3,
        estimated_duration_seconds=600,
    )


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


def test_generate_parses_newline_delimited_titles() -> None:
    stub = _StubLLMService(
        content="Deep Sea Wonders\nExploring the Ocean Floor\nHidden Life Below",
    )

    service = SEOTitleGenerationService(
        llm_service=stub,  # type: ignore[arg-type]
    )

    candidates = service.generate(_context(), candidate_count=3)

    assert [candidate.text for candidate in candidates] == [
        "Deep Sea Wonders",
        "Exploring the Ocean Floor",
        "Hidden Life Below",
    ]


def test_generate_strips_numbering_bullets_and_quotes() -> None:
    stub = _StubLLMService(
        content='1. "Deep Sea Wonders"\n- Exploring the Ocean Floor\n* Hidden Life',
    )

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    candidates = service.generate(_context(), candidate_count=3)

    assert [candidate.text for candidate in candidates] == [
        "Deep Sea Wonders",
        "Exploring the Ocean Floor",
        "Hidden Life",
    ]


def test_generate_deduplicates_case_insensitively() -> None:
    stub = _StubLLMService(
        content="Deep Sea Wonders\ndeep sea wonders\nHidden Life Below",
    )

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    candidates = service.generate(_context(), candidate_count=5)

    assert [candidate.text for candidate in candidates] == [
        "Deep Sea Wonders",
        "Hidden Life Below",
    ]


def test_generate_truncates_to_candidate_count() -> None:
    stub = _StubLLMService(content="Title A\nTitle B\nTitle C\nTitle D")

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    candidates = service.generate(_context(), candidate_count=2)

    assert len(candidates) == 2


def test_generate_includes_context_in_prompt() -> None:
    stub = _StubLLMService(content="Title A")

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(_context(), candidate_count=1)

    assert stub.last_request is not None
    assert "Deep sea creatures" in stub.last_request.prompt
    assert "Deep Sea Creatures Explained" in stub.last_request.prompt
    assert "Ocean enthusiasts" in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="SEO title generation failed"):
        service.generate(_context())


def test_generate_raises_on_empty_content() -> None:
    stub = _StubLLMService(content="   ")

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty content"):
        service.generate(_context())


def test_generate_rejects_candidate_count_below_one() -> None:
    stub = _StubLLMService(content="Title A")

    service = SEOTitleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least 1"):
        service.generate(_context(), candidate_count=0)


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content="Title A")

    with pytest.raises(ValueError, match="cannot be negative"):
        SEOTitleGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )
