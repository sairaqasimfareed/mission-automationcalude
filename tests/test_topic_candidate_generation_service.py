from __future__ import annotations

import pytest

from src.models.enums import Platform
from src.services.llm.llm_service import LLMServiceResult
from src.services.topic_candidate_generation_service import (
    TopicCandidateGenerationService,
)
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


_TWO_CANDIDATE_BLOCK = (
    "TITLE: The Missing Logbook of the Mary Celeste\n"
    "AUDIENCE_POTENTIAL: 80\n"
    "SPECIFICITY: 70\n"
    "NOVELTY: 60\n"
    "STORY_POTENTIAL: 90\n"
    "RESEARCHABILITY: 50\n"
    "PLATFORM_FIT: 65\n"
    "AI_RECOMMENDATION: Strong hook, well-documented case.\n"
    "---\n"
    "title: Ghost ships throughout history\n"
    "audience_potential: 55\n"
    "specificity: 30\n"
    "novelty: 40\n"
    "story_potential: 50\n"
    "researchability: 60\n"
    "platform_fit: 55\n"
    "ai_recommendation: Broader but less specific angle."
)


def test_generate_parses_multiple_candidate_blocks() -> None:
    stub = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    candidates = service.generate(
        seed_idea="The Mary Celeste",
        genre_id="genre.mystery",
        platform=Platform.YOUTUBE,
        candidate_count=2,
    )

    assert len(candidates) == 2
    assert candidates[0].title == "The Missing Logbook of the Mary Celeste"
    assert candidates[0].audience_potential == 80
    assert candidates[0].overall_score == pytest.approx(
        (80 + 70 + 60 + 90 + 50 + 65) / 6
    )
    assert candidates[1].title == "Ghost ships throughout history"


def test_generate_truncates_to_candidate_count() -> None:
    stub = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    candidates = service.generate(
        seed_idea="The Mary Celeste",
        genre_id="genre.mystery",
        platform=Platform.YOUTUBE,
        candidate_count=1,
    )

    assert len(candidates) == 1


def test_generate_skips_blocks_with_incomplete_scores() -> None:
    content = (
        "TITLE: Missing a score\n"
        "AUDIENCE_POTENTIAL: 80\n"
        "SPECIFICITY: 70\n"
        "AI_RECOMMENDATION: Should be skipped, missing scores.\n"
        "---\n"
        "TITLE: Fully scored candidate\n"
        "AUDIENCE_POTENTIAL: 60\n"
        "SPECIFICITY: 60\n"
        "NOVELTY: 60\n"
        "STORY_POTENTIAL: 60\n"
        "RESEARCHABILITY: 60\n"
        "PLATFORM_FIT: 60\n"
        "AI_RECOMMENDATION: Complete."
    )

    stub = _StubLLMService(content=content)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    candidates = service.generate(
        seed_idea="The Mary Celeste",
        genre_id="genre.mystery",
        platform=Platform.YOUTUBE,
        candidate_count=5,
    )

    assert len(candidates) == 1
    assert candidates[0].title == "Fully scored candidate"


def test_generate_skips_blocks_with_out_of_range_scores() -> None:
    content = (
        "TITLE: Bad score\n"
        "AUDIENCE_POTENTIAL: 150\n"
        "SPECIFICITY: 60\n"
        "NOVELTY: 60\n"
        "STORY_POTENTIAL: 60\n"
        "RESEARCHABILITY: 60\n"
        "PLATFORM_FIT: 60\n"
        "AI_RECOMMENDATION: Out of range, should be skipped."
    )

    stub = _StubLLMService(content=content)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable candidates"):
        service.generate(
            seed_idea="The Mary Celeste",
            genre_id="genre.mystery",
            platform=Platform.YOUTUBE,
        )


def test_generate_includes_seed_idea_genre_and_platform_in_prompt() -> None:
    stub = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        seed_idea="The Mary Celeste",
        genre_id="genre.mystery",
        platform=Platform.TIKTOK,
    )

    assert stub.last_request is not None
    assert "The Mary Celeste" in stub.last_request.prompt
    assert "genre.mystery" in stub.last_request.prompt
    assert "tiktok" in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Topic candidate generation failed"):
        service.generate(
            seed_idea="The Mary Celeste",
            genre_id="genre.mystery",
            platform=Platform.YOUTUBE,
        )


def test_generate_raises_when_no_valid_candidates_parsed() -> None:
    stub = _StubLLMService(content="This is not formatted correctly at all.")

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable candidates"):
        service.generate(
            seed_idea="The Mary Celeste",
            genre_id="genre.mystery",
            platform=Platform.YOUTUBE,
        )


def test_generate_rejects_candidate_count_below_one() -> None:
    stub = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least 1"):
        service.generate(
            seed_idea="The Mary Celeste",
            genre_id="genre.mystery",
            platform=Platform.YOUTUBE,
            candidate_count=0,
        )


def test_generate_rejects_empty_seed_idea() -> None:
    stub = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    service = TopicCandidateGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.generate(
            seed_idea="   ",
            genre_id="genre.mystery",
            platform=Platform.YOUTUBE,
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        TopicCandidateGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_CANDIDATE_BLOCK)

    service = TopicCandidateGenerationService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        seed_idea="The Mary Celeste",
        genre_id="genre.mystery",
        platform=Platform.YOUTUBE,
        candidate_count=3,
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = TopicCandidateGenerationService(llm_service=replay)  # type: ignore[arg-type]

    candidates = replay_service.generate(
        seed_idea="The Mary Celeste",
        genre_id="genre.mystery",
        platform=Platform.YOUTUBE,
        candidate_count=3,
    )

    assert len(candidates) == 3
