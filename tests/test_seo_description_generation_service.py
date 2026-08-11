from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.services.llm.llm_service import LLMServiceResult
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_description_generation_service import (
    SEODescriptionGenerationService,
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
        key_facts=["Fact one."],
        scene_count=1,
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


def test_generate_returns_stripped_description() -> None:
    stub = _StubLLMService(content="  A deep dive into ocean life.  ")

    service = SEODescriptionGenerationService(
        llm_service=stub,  # type: ignore[arg-type]
    )

    description = service.generate(
        _context(),
        selected_title="Deep Sea Creatures Explained",
    )

    assert description == "A deep dive into ocean life."


def test_generate_includes_selected_title_and_script_in_prompt() -> None:
    stub = _StubLLMService(content="A deep dive into ocean life.")

    service = SEODescriptionGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(_context(), selected_title="Deep Sea Wonders")

    assert stub.last_request is not None
    assert "Deep Sea Wonders" in stub.last_request.prompt
    assert "Full script content about deep sea creatures." in (stub.last_request.prompt)


def test_generate_raises_on_empty_selected_title() -> None:
    stub = _StubLLMService(content="A description.")

    service = SEODescriptionGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="selected title is required"):
        service.generate(_context(), selected_title="   ")


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = SEODescriptionGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="SEO description generation failed"):
        service.generate(_context(), selected_title="Deep Sea Creatures Explained")


def test_generate_raises_on_empty_content() -> None:
    stub = _StubLLMService(content="   ")

    service = SEODescriptionGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty content"):
        service.generate(_context(), selected_title="Deep Sea Creatures Explained")


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content="A description.")

    with pytest.raises(ValueError, match="cannot be negative"):
        SEODescriptionGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )
