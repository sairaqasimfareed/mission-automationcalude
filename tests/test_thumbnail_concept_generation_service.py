from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.services.llm.llm_service import LLMServiceResult
from src.services.seo.seo_context_builder import SEOContext
from src.services.thumbnail.thumbnail_concept_generation_service import (
    ThumbnailConceptGenerationService,
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


_TWO_CONCEPT_BLOCK = (
    "CONCEPT: A diver facing a giant squid.\n"
    "HOOK: GIANT SQUID ATTACK\n"
    "PROMPT: A deep sea diver facing a giant squid, dramatic lighting.\n"
    "---\n"
    "concept: A glowing anglerfish in darkness.\n"
    "hook: THE OCEAN'S SCARIEST FISH\n"
    "prompt: A glowing anglerfish lure in pitch black water."
)


def test_generate_parses_multiple_concept_blocks() -> None:
    stub = _StubLLMService(content=_TWO_CONCEPT_BLOCK)

    service = ThumbnailConceptGenerationService(
        llm_service=stub,  # type: ignore[arg-type]
    )

    concepts = service.generate(_context(), concept_count=2)

    assert len(concepts) == 2
    assert concepts[0].hook_text == "GIANT SQUID ATTACK"
    assert concepts[0].concept_summary == "A diver facing a giant squid."
    assert "giant squid" in concepts[0].visual_prompt.lower()
    assert concepts[1].hook_text == "THE OCEAN'S SCARIEST FISH"


def test_generate_truncates_to_concept_count() -> None:
    stub = _StubLLMService(content=_TWO_CONCEPT_BLOCK)

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    concepts = service.generate(_context(), concept_count=1)

    assert len(concepts) == 1


def test_generate_skips_blocks_missing_a_required_field() -> None:
    content = (
        "CONCEPT: A diver facing a giant squid.\n"
        "HOOK: GIANT SQUID ATTACK\n"
        "---\n"
        "CONCEPT: A glowing anglerfish in darkness.\n"
        "HOOK: THE OCEAN'S SCARIEST FISH\n"
        "PROMPT: A glowing anglerfish lure in pitch black water."
    )

    stub = _StubLLMService(content=content)

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    concepts = service.generate(_context(), concept_count=5)

    assert len(concepts) == 1
    assert concepts[0].hook_text == "THE OCEAN'S SCARIEST FISH"


def test_generate_includes_context_in_prompt() -> None:
    stub = _StubLLMService(content=_TWO_CONCEPT_BLOCK)

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        _context(),
        concept_count=1,
        selected_seo_title="Deep Sea Wonders",
    )

    assert stub.last_request is not None
    assert "Deep sea creatures" in stub.last_request.prompt
    assert "Deep Sea Creatures Explained" in stub.last_request.prompt
    assert "Deep Sea Wonders" in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Thumbnail concept generation failed"):
        service.generate(_context())


def test_generate_raises_on_empty_content() -> None:
    stub = _StubLLMService(content="   ")

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty content"):
        service.generate(_context())


def test_generate_raises_when_no_valid_concepts_parsed() -> None:
    stub = _StubLLMService(content="This is not formatted correctly at all.")

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable concepts"):
        service.generate(_context())


def test_generate_rejects_concept_count_below_one() -> None:
    stub = _StubLLMService(content=_TWO_CONCEPT_BLOCK)

    service = ThumbnailConceptGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least 1"):
        service.generate(_context(), concept_count=0)


def test_dry_run_response_is_itself_parseable() -> None:
    """
    Regression test: DryRunProviderAdapter returns LLMRequest's
    dry_run_response verbatim as its content when set (see
    dry_run_provider.py). This proves that response round-trips
    through _parse_concepts() successfully - without it,
    MISSION_AUTOMATION_DRY_RUN could never produce a thumbnail, since
    the adapter's old generic filler text had no CONCEPT/HOOK/PROMPT
    labels for the parser to find.
    """

    probe = _StubLLMService(content=_TWO_CONCEPT_BLOCK)

    service = ThumbnailConceptGenerationService(
        llm_service=probe,  # type: ignore[arg-type]
    )

    service.generate(_context(), concept_count=3)

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = ThumbnailConceptGenerationService(
        llm_service=replay,  # type: ignore[arg-type]
    )

    concepts = replay_service.generate(_context(), concept_count=3)

    assert len(concepts) == 3
    assert all(concept.hook_text for concept in concepts)


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_CONCEPT_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        ThumbnailConceptGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )
