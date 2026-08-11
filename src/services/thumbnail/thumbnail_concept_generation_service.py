from __future__ import annotations

import re

from src.models.thumbnail import ThumbnailConcept
from src.services.llm.llm_service import LLMService
from src.services.seo.seo_context_builder import SEOContext
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_BLOCK_SEPARATOR_PATTERN = re.compile(r"\n\s*-{3,}\s*\n")


class ThumbnailConceptGenerationService:
    """
    Generate candidate thumbnail concepts through the central LLM
    service.

    Each concept pairs a short hook text with a visual prompt, so
    output is requested as labeled plain-text blocks rather than JSON
    - matching the existing ScriptAgent/ResearchAgent/
    SEOTitleGenerationService convention, and avoiding the same
    dry-run adapter JSON-shape mismatch documented in
    SEOTitleGenerationService.

    Concept ranking is handled separately
    (ThumbnailConceptScoringService).
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated thumbnail concept cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        context: SEOContext,
        *,
        concept_count: int = 3,
        selected_seo_title: str | None = None,
    ) -> list[ThumbnailConcept]:
        """Generate up to concept_count distinct thumbnail concepts."""

        if concept_count < 1:
            raise ValueError("Concept count must be at least 1.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                context,
                concept_count=concept_count,
                selected_seo_title=selected_seo_title,
            ),
            system_prompt=(
                "You are an expert YouTube thumbnail designer. Propose "
                "thumbnail concepts that accurately reflect the "
                "supplied script content. Do not invent claims the "
                "script does not support. Hook text must be short "
                "enough to read at a glance."
            ),
            prompt_version="thumbnail_concept_prompt_v1.0.0",
            metadata={
                "agent": "ThumbnailConceptGenerationService",
                "workflow": "thumbnail_concept",
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

            raise RuntimeError(f"Thumbnail concept generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Thumbnail concept provider returned empty content.")

        concepts = self._parse_concepts(content)

        if not concepts:
            raise RuntimeError(
                "Thumbnail concept provider returned no usable concepts."
            )

        return concepts[:concept_count]

    @staticmethod
    def _build_prompt(
        context: SEOContext,
        *,
        concept_count: int,
        selected_seo_title: str | None,
    ) -> str:
        title_line = (
            f"Selected video title: {selected_seo_title}\n"
            if selected_seo_title
            else ""
        )

        return (
            f"Propose {concept_count} distinct thumbnail concepts for "
            "the following video.\n\n"
            f"Topic: {context.topic}\n"
            f"Niche: {context.niche}\n"
            f"Target audience: {context.target_audience}\n"
            f"{title_line}"
            f"Script title: {context.script_title}\n\n"
            f"Script content:\n{context.script_content}\n\n"
            "Return each concept as a block with exactly these three "
            "labeled lines, and separate blocks with a line of three "
            "or more dashes:\n"
            "CONCEPT: <one-sentence description of the visual concept>\n"
            "HOOK: <short on-image hook text, under 8 words>\n"
            "PROMPT: <detailed AI image-generation prompt>"
        )

    @classmethod
    def _parse_concepts(cls, content: str) -> list[ThumbnailConcept]:
        blocks = _BLOCK_SEPARATOR_PATTERN.split(content.strip())

        concepts: list[ThumbnailConcept] = []

        for block in blocks:
            concept_summary = cls._extract_field(block, "CONCEPT")
            hook_text = cls._extract_field(block, "HOOK")
            visual_prompt = cls._extract_field(block, "PROMPT")

            if not (concept_summary and hook_text and visual_prompt):
                continue

            concepts.append(
                ThumbnailConcept(
                    concept_summary=concept_summary,
                    hook_text=hook_text,
                    visual_prompt=visual_prompt,
                )
            )

        return concepts

    @staticmethod
    def _extract_field(block: str, label: str) -> str | None:
        pattern = re.compile(
            rf"^\s*{label}\s*:\s*(.+)$",
            re.IGNORECASE | re.MULTILINE,
        )

        match = pattern.search(block)

        if match is None:
            return None

        value = match.group(1).strip()

        return value or None
