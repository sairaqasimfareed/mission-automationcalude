from __future__ import annotations

import re

from src.models.seo import TitleCandidate
from src.services.llm.llm_service import LLMService
from src.services.seo.seo_context_builder import SEOContext
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_LEADING_MARKER_PATTERN = re.compile(r"^[\d]+[\.\)]\s*|^[-*•]\s*")


class SEOTitleGenerationService:
    """
    Generate candidate video titles through the central LLM service.

    Scoring and ranking are handled separately (SEOTitleScoringService)
    - this service is only responsible for producing distinct, on-topic
    candidate titles. Candidates are requested as plain newline-delimited
    text rather than JSON, matching the existing ScriptAgent/ResearchAgent
    convention, since no agent in this codebase currently relies on
    expect_json/parsed_data.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated SEO title cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        context: SEOContext,
        *,
        candidate_count: int = 5,
    ) -> list[TitleCandidate]:
        """Generate up to candidate_count distinct candidate titles."""

        if candidate_count < 1:
            raise ValueError("Candidate count must be at least 1.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                context,
                candidate_count=candidate_count,
            ),
            system_prompt=(
                "You are an expert YouTube title writer. Write titles "
                "that accurately reflect the supplied script content. "
                "Do not invent claims the script does not support. "
                "Avoid misleading or clickbait phrasing."
            ),
            prompt_version="seo_title_prompt_v1.0.0",
            metadata={
                "agent": "SEOTitleGenerationService",
                "workflow": "seo_title",
                "video_job_id": str(context.video_job_id),
                "topic": context.topic,
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(f"SEO title generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("SEO title provider returned empty content.")

        candidates = self._parse_candidates(content)

        if not candidates:
            raise RuntimeError(
                "SEO title provider returned no usable title candidates."
            )

        return candidates[:candidate_count]

    @staticmethod
    def _build_prompt(
        context: SEOContext,
        *,
        candidate_count: int,
    ) -> str:
        return (
            f"Write {candidate_count} distinct candidate YouTube titles "
            "for the following video.\n\n"
            f"Topic: {context.topic}\n"
            f"Niche: {context.niche}\n"
            f"Target audience: {context.target_audience}\n"
            f"Language: {context.language}\n\n"
            f"Script title: {context.script_title}\n\n"
            f"Script content:\n{context.script_content}\n\n"
            "Return exactly one title per line, with no numbering, "
            "quotation marks, or additional commentary."
        )

    @staticmethod
    def _parse_candidates(content: str) -> list[TitleCandidate]:
        """Parse newline-delimited title text into unique candidates."""

        seen: set[str] = set()
        candidates: list[TitleCandidate] = []

        for line in content.splitlines():
            cleaned = _LEADING_MARKER_PATTERN.sub("", line.strip())
            cleaned = cleaned.strip().strip('"').strip("'").strip()

            if not cleaned:
                continue

            normalized = cleaned.lower()

            if normalized in seen:
                continue

            seen.add(normalized)
            candidates.append(TitleCandidate(text=cleaned))

        return candidates
