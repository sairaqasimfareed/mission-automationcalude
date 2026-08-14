from __future__ import annotations

from src.models.audience_promise import AudiencePromise
from src.models.hook import HookCandidate
from src.models.research import ResearchResult
from src.models.story_angle import StoryAngle
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_DRY_RUN_RESPONSE = "\n---\n".join(
    f"TEXT: Dry-run hook candidate {ordinal} for development and "
    "testing purposes only."
    for ordinal in ("one", "two", "three", "four", "five")
)


class HookGenerationService:
    """
    Generates multiple candidate opening hooks through the central
    LLM service (spec section 28).

    Candidate count is configurable (spec suggests a typical range of
    5-20) rather than fixed, and every candidate is grounded in the
    selected story angle and research so hooks stay factually
    supported rather than generically clickbait-y.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated hook generation cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        topic: str,
        story_angle: StoryAngle,
        audience_promise: AudiencePromise,
        research: ResearchResult,
        hook_count: int = 10,
    ) -> list[HookCandidate]:
        """Generate up to hook_count distinct candidate hooks."""

        if hook_count < 1:
            raise ValueError("Hook count must be at least 1.")

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Hook generation topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                story_angle=story_angle,
                audience_promise=audience_promise,
                research=research,
                hook_count=hook_count,
            ),
            system_prompt=(
                "You are an expert video hook writer. Write opening "
                "lines that create immediate curiosity without "
                "misleading the viewer. Never state a claim the "
                "research does not support, never fully spoil the "
                "payoff, and never open with a greeting or generic "
                "introduction."
            ),
            prompt_version="hook_generation_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "HookGenerationService",
                "workflow": "hook_generation",
                "topic": normalized_topic,
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

            raise RuntimeError(f"Hook generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Hook generation provider returned empty content.")

        hooks = self._parse_hooks(content)

        if not hooks:
            raise RuntimeError("Hook generation provider returned no usable hooks.")

        return hooks[:hook_count]

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        story_angle: StoryAngle,
        audience_promise: AudiencePromise,
        research: ResearchResult,
        hook_count: int,
    ) -> str:
        return (
            f"Topic: {topic}\n"
            f"Selected angle [{story_angle.style.value}]: {story_angle.title} - "
            f"{story_angle.description}\n"
            f"Central curiosity: {audience_promise.central_curiosity}\n"
            f"Research summary: {research.research_summary}\n\n"
            f"Write {hook_count} distinct candidate opening hooks for "
            "this video. Each hook must create immediate curiosity, "
            "be specific rather than generic, and never fully reveal "
            "the payoff.\n\n"
            "Return each hook as a block with exactly this labeled "
            "line, separated by a line of three or more dashes:\n"
            "TEXT: <the hook, one to two sentences>"
        )

    @staticmethod
    def _parse_hooks(content: str) -> list[HookCandidate]:
        hooks: list[HookCandidate] = []

        for block in split_blocks(content):
            text = extract_labeled_field(block, "TEXT")

            if not text:
                continue

            hooks.append(HookCandidate(text=text))

        return hooks
