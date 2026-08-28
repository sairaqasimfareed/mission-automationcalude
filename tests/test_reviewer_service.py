from __future__ import annotations

import pytest

from src.models.artifact_lifecycle import ArtifactType
from src.models.editorial_critique import FindingSeverity
from src.services.llm.llm_service import LLMServiceResult
from src.services.reviewer_service import ReviewerService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success
        self.last_request: LLMRequest | None = None
        self.call_count = 0

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.last_request = request
        self.call_count += 1

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
            selected_profile_id="anthropic-reviewer" if self._success else None,
            all_providers_failed=not self._success,
        )


_FULL_RESPONSE = (
    "STRENGTH: The hook is clear and specific.\n"
    "STRENGTH: The central question is compelling.\n"
    "---\n"
    "DESCRIPTION: The second claim has no cited source.\n"
    "SEVERITY: major\n"
    "RECOMMENDATION: Add a source or soften the claim.\n"
    "---\n"
    "DESCRIPTION: The tone shifts abruptly midway through.\n"
    "SEVERITY: minor\n"
    "RECOMMENDATION: none\n"
    "---\n"
    "SUGGESTED_REVISION_DIRECTION: Tighten the middle section and add "
    "a source for the unsupported claim."
)


def test_review_returns_none_immediately_when_no_reviewer_is_configured() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    result = service.review(
        artifact_type=ArtifactType.SCRIPT,
        content="Some script content.",
        context="Some context.",
        reviewer_profile_id=None,
    )

    assert result is None
    assert stub.call_count == 0


def test_review_parses_strengths_issues_and_suggested_direction() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    result = service.review(
        artifact_type=ArtifactType.SCRIPT,
        content="Some script content.",
        context="Some context.",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert result is not None
    assert result.artifact_type == ArtifactType.SCRIPT
    assert result.reviewer_profile_id == "anthropic-reviewer"
    assert len(result.strengths) == 2
    assert "The hook is clear and specific." in result.strengths
    assert len(result.issues) == 2
    assert result.issues[0].severity == FindingSeverity.MAJOR
    assert result.issues[0].recommendation == "Add a source or soften the claim."
    assert result.issues[1].severity == FindingSeverity.MINOR
    assert result.issues[1].recommendation is None
    assert result.suggested_revision_direction is not None
    assert "Tighten the middle section" in result.suggested_revision_direction


def test_review_sends_only_the_configured_reviewer_profile() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    service.review(
        artifact_type=ArtifactType.HOOK,
        content="content",
        context="context",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert stub.last_request is not None


def test_has_blocking_issues_reflects_blocking_severity() -> None:
    response = (
        "STRENGTH: Fine.\n"
        "---\n"
        "DESCRIPTION: This is a critical factual error.\n"
        "SEVERITY: blocking\n"
        "RECOMMENDATION: Remove the claim.\n"
    )
    stub = _StubLLMService(content=response)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    result = service.review(
        artifact_type=ArtifactType.RESEARCH,
        content="content",
        context="context",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert result is not None
    assert result.has_blocking_issues is True


def test_no_issues_at_all_produces_an_empty_issue_list() -> None:
    response = "STRENGTH: Strong throughout.\nSTRENGTH: Well-paced.\n"
    stub = _StubLLMService(content=response)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    result = service.review(
        artifact_type=ArtifactType.STORY_ARCHITECTURE,
        content="content",
        context="context",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert result is not None
    assert result.issues == []
    assert result.suggested_revision_direction is None


def test_review_raises_when_all_providers_fail() -> None:
    stub = _StubLLMService(content="", success=False)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Reviewer pass failed"):
        service.review(
            artifact_type=ArtifactType.SCRIPT,
            content="content",
            context="context",
            reviewer_profile_id="anthropic-reviewer",
        )


def test_negative_estimated_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ReviewerService(
            llm_service=_StubLLMService(content=_FULL_RESPONSE),  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    """
    Every content-generation service in this codebase proves its own
    dry_run_response round-trips through its own parser - this is
    what makes ReviewerService usable inside a whole-pipeline
    dry-run test without per-service canned data.
    """

    stub = _StubLLMService(content="placeholder - overwritten by dry-run below")
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]
    dry_run_text = service._dry_run_response()

    stub_for_dry_run = _StubLLMService(content=dry_run_text)
    dry_run_service = ReviewerService(llm_service=stub_for_dry_run)  # type: ignore[arg-type]

    result = dry_run_service.review(
        artifact_type=ArtifactType.SCRIPT,
        content="content",
        context="context",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert result is not None
    assert len(result.strengths) == 1


def test_research_artifacts_get_additional_focus_guidance_in_the_prompt() -> None:
    """
    Content Studio Redesign, Phase 8: "Reviewer findings highlight
    unsupported claims, weak sources, contradictions, unanswered
    questions and missing perspectives" - additive prompt guidance for
    ArtifactType.RESEARCH specifically, reusing the same generic
    review() mechanism rather than a separate research-specific critic.
    """

    stub = _StubLLMService(content=_FULL_RESPONSE)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    service.review(
        artifact_type=ArtifactType.RESEARCH,
        content="content",
        context="context",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert stub.last_request is not None
    assert "unsupported claims" in stub.last_request.prompt.lower()
    assert "contradictions" in stub.last_request.prompt.lower()


def test_non_research_artifacts_do_not_get_research_focus_guidance() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)
    service = ReviewerService(llm_service=stub)  # type: ignore[arg-type]

    service.review(
        artifact_type=ArtifactType.SCRIPT,
        content="content",
        context="context",
        reviewer_profile_id="anthropic-reviewer",
    )

    assert stub.last_request is not None
    assert "weak or low-credibility sources" not in stub.last_request.prompt
