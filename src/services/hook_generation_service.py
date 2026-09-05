from __future__ import annotations

from uuid import UUID

from src.models.audience_promise import AudiencePromise
from src.models.editorial_profile import EditorialProfile
from src.models.genre_profile import HookArchetype
from src.models.hook import HookCandidate
from src.models.research import ResearchResult
from src.models.research_evidence import ResearchFact
from src.models.story_angle import StoryAngle
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_VALID_ARCHETYPES = {archetype.value for archetype in HookArchetype}

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
        editorial_profile: EditorialProfile,
        hook_count: int = 10,
        additional_instructions: str | None = None,
    ) -> list[HookCandidate]:
        """
        Generate up to hook_count distinct candidate hooks.

        When research has structured_facts (Phase 8's evidence
        ledger), each hook can be bound to the facts it draws on
        ("fact IDs" in the redesign's hook schema) and to a
        HookArchetype ("type"). additional_instructions is free-text
        guidance for a targeted rewrite (e.g. "make it more
        suspenseful") rather than a from-scratch generation.
        """

        if hook_count < 1:
            raise ValueError("Hook count must be at least 1.")

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Hook generation topic cannot be empty.")

        facts = list(research.structured_facts)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                story_angle=story_angle,
                audience_promise=audience_promise,
                research=research,
                editorial_profile=editorial_profile,
                hook_count=hook_count,
                facts=facts,
                additional_instructions=additional_instructions,
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

        hooks = self._parse_hooks(content, facts=facts)

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
        editorial_profile: EditorialProfile,
        hook_count: int,
        facts: list[ResearchFact],
        additional_instructions: str | None,
    ) -> str:
        content_intelligence = editorial_profile.content_intelligence

        archetype_guidance = ""

        if content_intelligence.preferred_hook_archetypes:
            preferred = ", ".join(
                archetype.value
                for archetype in content_intelligence.preferred_hook_archetypes
            )
            archetype_guidance += f"Preferred hook archetypes: {preferred}\n"

        if content_intelligence.forbidden_hook_archetypes:
            forbidden = ", ".join(
                archetype.value
                for archetype in content_intelligence.forbidden_hook_archetypes
            )
            archetype_guidance += f"Forbidden hook archetypes: {forbidden}\n"

        facts_section = ""

        if facts:
            fact_lines = "\n".join(
                f"FACT_{index}: {fact.text}"
                for index, fact in enumerate(facts, start=1)
            )
            facts_section = (
                f"\nVerified facts available to draw on:\n{fact_lines}\n"
                "For each hook, if it relies on any of these facts, add "
                "a line FACT_IDS: <comma-separated fact numbers, or "
                "'none'>.\n"
            )

        instructions_section = (
            f"\nAdditional instruction: {additional_instructions}\n"
            if additional_instructions
            else ""
        )

        available_archetypes = ", ".join(archetype.value for archetype in HookArchetype)

        return (
            f"Topic: {topic}\n"
            f"Genre hook style: {editorial_profile.script.hook_style}\n"
            f"Hook intensity: {content_intelligence.hook_intensity.value}\n"
            f"{archetype_guidance}"
            f"Selected angle [{story_angle.style.value}]: {story_angle.title} - "
            f"{story_angle.description}\n"
            f"Central curiosity: {audience_promise.central_curiosity}\n"
            f"Research summary: {research.research_summary}\n"
            f"{facts_section}"
            f"{instructions_section}\n"
            f"Write {hook_count} distinct candidate opening hooks for "
            "this video, matching the genre hook style and intensity "
            "above. Each hook must create immediate curiosity, be "
            "specific rather than generic, and never fully reveal "
            "the payoff.\n\n"
            "Return each hook as a block, separated by a line of three "
            "or more dashes, with:\n"
            "TEXT: <the hook, one to two sentences>\n"
            "HOOK_ARCHETYPE: <optional, one of: "
            f"{available_archetypes} - or omit this line>"
        )

    @classmethod
    def _parse_hooks(
        cls, content: str, *, facts: list[ResearchFact]
    ) -> list[HookCandidate]:
        hooks: list[HookCandidate] = []

        for block in split_blocks(content):
            text = extract_labeled_field(block, "TEXT")

            if not text:
                continue

            archetype = cls._parse_archetype(block)
            fact_ids = cls._parse_fact_ids(block, facts=facts)

            hooks.append(HookCandidate(text=text, type=archetype, fact_ids=fact_ids))

        return hooks

    @staticmethod
    def _parse_archetype(block: str) -> HookArchetype | None:
        raw = extract_labeled_field(block, "HOOK_ARCHETYPE")

        if raw is None:
            return None

        normalized = raw.strip().lower()

        if normalized not in _VALID_ARCHETYPES:
            return None

        return HookArchetype(normalized)

    @staticmethod
    def _parse_fact_ids(block: str, *, facts: list[ResearchFact]) -> list[UUID]:
        if not facts:
            return []

        raw = extract_labeled_field(block, "FACT_IDS")

        if raw is None or raw.strip().lower() == "none":
            return []

        fact_ids: list[UUID] = []

        for token in raw.split(","):
            token = token.strip()

            if not token.isdigit():
                continue

            index = int(token)

            if 1 <= index <= len(facts):
                fact_ids.append(facts[index - 1].id)

        return fact_ids
