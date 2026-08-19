from __future__ import annotations

import re

from src.models.audience_promise import AudiencePromise
from src.models.editorial_profile import EditorialProfile
from src.models.research_plan import ResearchPlan
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_DRY_RUN_RESPONSE = "\n".join(
    f"- Dry-run research question {ordinal} for development and "
    "testing purposes only."
    for ordinal in ("one", "two", "three", "four")
)


class ResearchPlanningService:
    """
    Decides what should be researched for one topic, before deep
    research begins (spec section 13), so research stays purposeful
    rather than an uncontrolled information dump.

    Guided by the topic's AudiencePromise so the questions stay
    aligned with the promise the video will make to its viewer,
    instead of researching everything indiscriminately.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated research planning cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def plan(
        self,
        topic: str,
        audience_promise: AudiencePromise,
        editorial_profile: EditorialProfile,
    ) -> ResearchPlan:
        """Plan the research questions for one topic."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Research plan topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                audience_promise=audience_promise,
                editorial_profile=editorial_profile,
            ),
            system_prompt=(
                "You are an expert research planner for long-form "
                "video. List the specific questions research must "
                "answer before any research begins - do not answer "
                "them, only ask them. Prefer questions that are "
                "purposeful and directly serve the video's central "
                "promise over generic background questions."
            ),
            prompt_version="research_plan_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "ResearchPlanningService",
                "workflow": "research_planning",
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

            raise RuntimeError(f"Research planning failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Research planning provider returned empty content.")

        questions = self._parse_questions(content)

        if not questions:
            raise RuntimeError(
                "Research planning provider returned no usable questions."
            )

        return ResearchPlan(
            topic=normalized_topic,
            research_questions=questions,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        audience_promise: AudiencePromise,
        editorial_profile: EditorialProfile,
    ) -> str:
        research_policy = editorial_profile.content_intelligence.research_policy

        return (
            f"Topic: {topic}\n"
            f"Central curiosity: {audience_promise.central_curiosity}\n"
            f"Primary question: {audience_promise.primary_question}\n"
            f"Expected payoff: {audience_promise.expected_payoff}\n"
            f"Required research depth: {research_policy.depth.value}\n"
            f"Primary sources required: "
            f"{'yes' if research_policy.requires_primary_sources else 'no'}\n"
            f"Uncertain-information policy: "
            f"{research_policy.uncertain_information_policy.value}\n\n"
            "List the research questions that must be answered to "
            "deliver on this promise, at a thoroughness matching the "
            "required research depth above. Consider: what happened, "
            "who was involved, when, where, what is verified, what "
            "remains unknown, what explanations exist, what "
            "contradictions exist, what details are commonly "
            "misreported, and which claims require stronger "
            "verification - but only include questions genuinely "
            "relevant to this topic.\n\n"
            "Return one question per line, each starting with '- '."
        )

    # Matches a leading "- ", "* ", or "1. " / "1) " style bullet -
    # tolerates numbered-list formatting some providers use despite
    # the requested "- " prefix.
    _BULLET_PATTERN = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+)$")

    @classmethod
    def _parse_questions(cls, content: str) -> list[str]:
        questions: list[str] = []

        for line in content.splitlines():
            match = cls._BULLET_PATTERN.match(line)

            if match is None:
                continue

            question = match.group(1).strip()

            if question and question not in questions:
                questions.append(question)

        return questions
