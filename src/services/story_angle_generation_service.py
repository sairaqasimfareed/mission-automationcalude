from __future__ import annotations

from src.models.audience_promise import AudiencePromise
from src.models.research import ResearchResult
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_VALID_STYLES = {style.value for style in StoryAngleStyle}

_DRY_RUN_RESPONSE = "\n---\n".join(
    f"STYLE: {style}\n"
    f"TITLE: Dry-run {style} angle for development and testing purposes only.\n"
    f"DESCRIPTION: Dry-run {style} angle description for development and "
    "testing purposes only."
    for style in ("mystery", "investigation", "question_driven")
)


class StoryAngleGenerationService:
    """
    Generates multiple candidate narrative framings for one topic
    through the central LLM service, before script writing (spec
    section 21).

    Candidates are grounded in the topic's research and audience
    promise so angles stay factually supported and aligned with what
    the video actually promises, rather than generic framings.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated story angle cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        topic: str,
        research: ResearchResult,
        audience_promise: AudiencePromise,
        angle_count: int = 5,
    ) -> list[StoryAngle]:
        """Generate up to angle_count distinct candidate story angles."""

        if angle_count < 1:
            raise ValueError("Angle count must be at least 1.")

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Story angle topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                research=research,
                audience_promise=audience_promise,
                angle_count=angle_count,
            ),
            system_prompt=(
                "You are an expert narrative strategist for long-form "
                "video. Propose distinct narrative framings for the "
                "supplied research. Only use a style genuinely suited "
                "to the topic and genre - do not force styles that "
                "don't fit. Never invent facts the research does not "
                "support."
            ),
            prompt_version="story_angle_generation_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "StoryAngleGenerationService",
                "workflow": "story_angle_generation",
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

            raise RuntimeError(f"Story angle generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Story angle provider returned empty content.")

        angles = self._parse_angles(content)

        if not angles:
            raise RuntimeError("Story angle provider returned no usable angles.")

        return angles[:angle_count]

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        research: ResearchResult,
        audience_promise: AudiencePromise,
        angle_count: int,
    ) -> str:
        available_styles = ", ".join(style.value for style in StoryAngleStyle)

        return (
            f"Topic: {topic}\n"
            f"Central curiosity: {audience_promise.central_curiosity}\n"
            f"Primary question: {audience_promise.primary_question}\n"
            f"Research summary: {research.research_summary}\n"
            f"Key facts: {'; '.join(research.key_facts)}\n\n"
            f"Propose {angle_count} distinct narrative angles for this "
            f"topic. Available styles: {available_styles}.\n\n"
            "Return each angle as a block with exactly these three "
            "labeled lines, and separate blocks with a line of three "
            "or more dashes:\n"
            "STYLE: <one style from the available list>\n"
            "TITLE: <short angle title>\n"
            "DESCRIPTION: <2-3 sentences describing this narrative "
            "framing and why it fits the research>"
        )

    @classmethod
    def _parse_angles(cls, content: str) -> list[StoryAngle]:
        angles: list[StoryAngle] = []

        for block in split_blocks(content):
            style_raw = extract_labeled_field(block, "STYLE")
            title = extract_labeled_field(block, "TITLE")
            description = extract_labeled_field(block, "DESCRIPTION")

            if not (style_raw and title and description):
                continue

            normalized_style = style_raw.strip().lower()

            if normalized_style not in _VALID_STYLES:
                continue

            angles.append(
                StoryAngle(
                    style=StoryAngleStyle(normalized_style),
                    title=title,
                    description=description,
                )
            )

        return angles
