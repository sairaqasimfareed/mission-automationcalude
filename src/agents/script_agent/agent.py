from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.script import (
    Script,
    ScriptStatus,
)
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class ScriptAgent:
    """Generates a draft script through the central LLM service."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated script cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        research: ResearchResult,
        *,
        target_duration_seconds: int | None = None,
    ) -> Script:
        """
        Generate one script from approved research.

        target_duration_seconds (2026-09-11 real fix, found live) lets
        a caller (ContentPipeline.run(), which already has
        VideoJob.target_duration_seconds available) scope the real
        prompt to the project's actual requested length. Before this,
        the prompt always asked for a "long-form" script regardless of
        what was requested - a real live test asking for a 40-second
        video got back a 1578-second (26-minute), 3631-word script,
        which the scene planner then had no sane way to turn into a
        real ~40-second scene list. None (the default) reproduces this
        method's exact prior behavior - still a real, honest choice
        for a genuinely long-form project, not a workaround.

        Word-count target uses the same ~2.3 words/second pace already
        used below for estimated_duration_seconds, so the guidance and
        this script's own self-reported duration stay consistent with
        each other.
        """

        if research.status != ResearchStatus.APPROVED:
            raise ValueError("Script generation requires approved research.")

        if target_duration_seconds is not None:
            target_word_count = max(round(target_duration_seconds * 2.3), 1)
            length_instruction = (
                "Write a YouTube script targeting approximately "
                f"{target_duration_seconds} seconds of narration "
                f"(about {target_word_count} words) when read aloud at "
                "a natural pace. Stay close to this length - do not "
                "write a long-form script. Write only the narration "
                "itself: no markdown headers, scene labels, channel "
                "branding, or production notes."
            )
        else:
            length_instruction = "Write a long-form YouTube script."

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=(
                f"{length_instruction} Use the following approved "
                "research:\n\n"
                f"Topic: {research.topic}\n\n"
                f"Research summary:\n"
                f"{research.research_summary}\n\n"
                "Key facts:\n" + "\n".join(f"- {fact}" for fact in research.key_facts)
            ),
            system_prompt=(
                "You are a professional YouTube scriptwriter. Write "
                "an original, engaging, well-structured and "
                "channel-specific script. Do not invent unsupported "
                "factual claims."
            ),
            prompt_version="script_prompt_v2.0.0",
            metadata={
                "agent": "ScriptAgent",
                "workflow": "script",
                "research_id": str(research.id),
                "topic": research.topic,
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

            raise RuntimeError("Script generation failed: " f"{error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Script provider returned empty content.")

        word_count = len(content.split())

        return Script(
            title=research.topic,
            content=content,
            prompt_version=request.prompt_version,
            word_count=word_count,
            estimated_duration_seconds=max(
                int(word_count / 2.3),
                1,
            ),
            status=ScriptStatus.UNDER_REVIEW,
        )
