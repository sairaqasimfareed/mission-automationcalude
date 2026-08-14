from __future__ import annotations

from src.models.information_reveal_map import (
    CuriosityLoop,
    InformationReveal,
    InformationRevealMap,
)
from src.models.research import ResearchResult
from src.models.story_angle import StoryAngle
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_YES_VALUES = {"yes", "true", "y"}

_DRY_RUN_RESPONSE = (
    "TYPE: loop\n"
    "QUESTION: Dry-run curiosity loop question for development and "
    "testing purposes only.\n"
    "OPENED_AT: 0.05\n"
    "ALLOW_EARLY_RESOLUTION: no\n"
    "---\n"
    "TYPE: reveal\n"
    "POSITION: 0.9\n"
    "INFORMATION: Dry-run payoff reveal for development and testing "
    "purposes only.\n"
    "ESCALATES: no\n"
    "IS_PAYOFF: yes\n"
    "RELATED_QUESTION: Dry-run curiosity loop question for "
    "development and testing purposes only."
)


class InformationRevealPlanningService:
    """
    Plans an InformationRevealMap for one story angle through the
    central LLM service, before prose generation begins (spec
    sections 24-25).

    Decides which major questions the story opens and when, and which
    pieces of information get revealed and when - so a later script
    generator has explicit guardrails against spoiling reveals early
    or leaving a major question unresolved.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated reveal map cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def plan(
        self,
        *,
        topic: str,
        story_angle: StoryAngle,
        research: ResearchResult,
    ) -> InformationRevealMap:
        """Plan the curiosity loops and information reveals for one angle."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Information reveal map topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                story_angle=story_angle,
                research=research,
            ),
            system_prompt=(
                "You are an expert story structure editor for "
                "long-form video. Plan which questions the story "
                "opens and when, and which pieces of information are "
                "revealed and when. Never let a major reveal happen "
                "before its question has been opened. Prefer a small "
                "number of well-developed questions over many shallow "
                "ones."
            ),
            prompt_version="information_reveal_map_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "InformationRevealPlanningService",
                "workflow": "information_reveal_planning",
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

            raise RuntimeError(f"Information reveal planning failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError(
                "Information reveal planning provider returned empty content."
            )

        loops, reveals = self._parse_blocks(content)

        if not loops:
            raise RuntimeError(
                "Information reveal planning provider returned no usable "
                "curiosity loops."
            )

        return InformationRevealMap(
            topic=normalized_topic,
            curiosity_loops=loops,
            reveals=reveals,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        story_angle: StoryAngle,
        research: ResearchResult,
    ) -> str:
        return (
            f"Topic: {topic}\n"
            f"Selected angle [{story_angle.style.value}]: {story_angle.title} - "
            f"{story_angle.description}\n"
            f"Research summary: {research.research_summary}\n\n"
            "Plan the story's curiosity loops and information reveals. "
            "Return one block per item, separated by a line of three "
            "or more dashes. Positions are normalized 0.0 (start) to "
            "1.0 (end) of the story's runtime.\n\n"
            "For each major question, return a block:\n"
            "TYPE: loop\n"
            "QUESTION: <the question this loop asks>\n"
            "OPENED_AT: <0.0-1.0>\n"
            "ALLOW_EARLY_RESOLUTION: <yes or no - yes only if this "
            "question should intentionally resolve quickly>\n\n"
            "For each information reveal, return a block:\n"
            "TYPE: reveal\n"
            "POSITION: <0.0-1.0>\n"
            "INFORMATION: <what is revealed at this point>\n"
            "ESCALATES: <yes or no - does this raise the stakes>\n"
            "IS_PAYOFF: <yes or no - does this resolve a question>\n"
            "RELATED_QUESTION: <the exact QUESTION text this reveal "
            "relates to, or 'none'>"
        )

    @classmethod
    def _parse_blocks(
        cls,
        content: str,
    ) -> tuple[list[CuriosityLoop], list[InformationReveal]]:
        loops: list[CuriosityLoop] = []
        reveals: list[InformationReveal] = []

        for block in split_blocks(content):
            block_type = (extract_labeled_field(block, "TYPE") or "").strip().lower()

            if block_type == "loop":
                loop = cls._parse_loop(block)

                if loop is not None:
                    loops.append(loop)
            elif block_type == "reveal":
                reveal = cls._parse_reveal(block)

                if reveal is not None:
                    reveals.append(reveal)

        return loops, reveals

    @classmethod
    def _parse_loop(cls, block: str) -> CuriosityLoop | None:
        question = extract_labeled_field(block, "QUESTION")
        opened_at_raw = extract_labeled_field(block, "OPENED_AT")
        allow_early_raw = extract_labeled_field(block, "ALLOW_EARLY_RESOLUTION")

        if not question or opened_at_raw is None:
            return None

        opened_at = cls._parse_fraction(opened_at_raw)

        if opened_at is None:
            return None

        try:
            return CuriosityLoop(
                question=question,
                opened_at_position=opened_at,
                allow_early_resolution=(
                    (allow_early_raw or "").strip().lower() in _YES_VALUES
                ),
            )
        except ValueError:
            return None

    @classmethod
    def _parse_reveal(cls, block: str) -> InformationReveal | None:
        position_raw = extract_labeled_field(block, "POSITION")
        information = extract_labeled_field(block, "INFORMATION")
        escalates_raw = extract_labeled_field(block, "ESCALATES")
        is_payoff_raw = extract_labeled_field(block, "IS_PAYOFF")
        related_question = extract_labeled_field(block, "RELATED_QUESTION")

        if not information or position_raw is None:
            return None

        position = cls._parse_fraction(position_raw)

        if position is None:
            return None

        normalized_related = (related_question or "").strip().lower()

        try:
            return InformationReveal(
                position=position,
                information=information,
                escalates_story=(escalates_raw or "").strip().lower() in _YES_VALUES,
                is_payoff=(is_payoff_raw or "").strip().lower() in _YES_VALUES,
                related_question=(
                    None if normalized_related == "none" else related_question
                ),
            )
        except ValueError:
            return None

    @staticmethod
    def _parse_fraction(raw: str) -> float | None:
        try:
            value = float(raw.strip())
        except ValueError:
            return None

        if not 0.0 <= value <= 1.0:
            return None

        return value
