from __future__ import annotations

from src.services.llm.llm_service import LLMService
from src.services.seo.seo_context_builder import SEOContext
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class SEODescriptionGenerationService:
    """
    Generate one publish-ready video description through the central
    LLM service.

    Description validity (length, emptiness, and so on) is checked
    separately by SEOValidationService - this service is only
    responsible for producing the description text.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated SEO description cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        context: SEOContext,
        *,
        selected_title: str,
    ) -> str:
        """Generate one publish-ready description for the selected title."""

        normalized_title = selected_title.strip()

        if not normalized_title:
            raise ValueError("A selected title is required to generate a description.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(context, selected_title=normalized_title),
            system_prompt=(
                "You are an expert YouTube description writer. Write "
                "a description that accurately reflects only the "
                "supplied script content and selected title. Do not "
                "invent facts, statistics, or promises the script "
                "does not support."
            ),
            prompt_version="seo_description_prompt_v1.0.0",
            metadata={
                "agent": "SEODescriptionGenerationService",
                "workflow": "seo_description",
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

            raise RuntimeError(f"SEO description generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("SEO description provider returned empty content.")

        return content

    @staticmethod
    def _build_prompt(
        context: SEOContext,
        *,
        selected_title: str,
    ) -> str:
        return (
            "Write a publish-ready YouTube video description for the "
            "following video.\n\n"
            f"Selected title: {selected_title}\n"
            f"Topic: {context.topic}\n"
            f"Niche: {context.niche}\n"
            f"Target audience: {context.target_audience}\n"
            f"Language: {context.language}\n\n"
            f"Script content:\n{context.script_content}\n\n"
            "The description must accurately represent this exact "
            "video, contain no unsupported claims or promises, and be "
            "suitable for direct publishing."
        )
