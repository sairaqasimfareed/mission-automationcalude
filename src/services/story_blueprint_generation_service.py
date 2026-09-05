from __future__ import annotations

from uuid import UUID

from src.models.audience_promise import AudiencePromise
from src.models.editorial_profile import EditorialProfile
from src.models.research import ResearchResult
from src.models.research_evidence import ResearchFact
from src.models.story_angle import StoryAngle
from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_VALID_BEAT_TYPES = {beat_type.value for beat_type in StoryBeatType}

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        (
            "BEAT_TYPE: hook\n"
            "START: 0\n"
            "END: 7\n"
            "PURPOSE: Dry-run hook purpose for development and "
            "testing purposes only.\n"
            "TENSION: 60"
        ),
        (
            "BEAT_TYPE: setup\n"
            "START: 7\n"
            "END: 20\n"
            "PURPOSE: Dry-run setup purpose for development and "
            "testing purposes only.\n"
            "TENSION: 30"
        ),
        (
            "BEAT_TYPE: climax\n"
            "START: 20\n"
            "END: 28\n"
            "PURPOSE: Dry-run climax purpose for development and "
            "testing purposes only.\n"
            "TENSION: 95"
        ),
        (
            "BEAT_TYPE: payoff\n"
            "START: 28\n"
            "END: 30\n"
            "PURPOSE: Dry-run payoff purpose for development and "
            "testing purposes only.\n"
            "TENSION: 50"
        ),
    ]
)


class StoryBlueprintGenerationService:
    """
    Plans the structural blueprint for one video through the central
    LLM service, before full narration begins (spec section 26).

    Beat sequence, count, and timing are entirely decided by the LLM
    call based on genre, duration, and the selected story angle - this
    service does not hardcode any fixed beat template, per spec
    section 26's explicit warning against exactly that.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated story blueprint cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        topic: str,
        editorial_profile: EditorialProfile,
        target_duration_seconds: int,
        story_angle: StoryAngle,
        audience_promise: AudiencePromise,
        research: ResearchResult | None = None,
        additional_instructions: str | None = None,
    ) -> StoryBlueprint:
        """
        Generate a duration- and genre-aware structural blueprint.

        research is optional and additive - when supplied and it has
        structured_facts (Phase 8's evidence ledger), each beat can be
        bound to the facts it draws on ("Evidence Allocation") and the
        blueprint records research.id ("Architecture references
        approved Research version"). Without research, behavior is
        identical to before this phase existed. additional_instructions
        is free-text guidance appended to the prompt (e.g. "compress
        the slow middle section") for a targeted regeneration rather
        than a from-scratch one.
        """

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Story blueprint topic cannot be empty.")

        facts = list(research.structured_facts) if research is not None else []

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                editorial_profile=editorial_profile,
                target_duration_seconds=target_duration_seconds,
                story_angle=story_angle,
                audience_promise=audience_promise,
                facts=facts,
                additional_instructions=additional_instructions,
            ),
            system_prompt=(
                "You are an expert story structure editor for "
                "long-form video. Design a beat-by-beat structural "
                "blueprint tailored to this genre and duration - do "
                "not reuse a generic template. Vary tension over time "
                "rather than keeping it at maximum throughout; use "
                "small releases before stronger escalation."
            ),
            prompt_version="story_blueprint_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "StoryBlueprintGenerationService",
                "workflow": "story_blueprint_generation",
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

            raise RuntimeError(f"Story blueprint generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Story blueprint provider returned empty content.")

        beats = self._parse_beats(content, facts=facts)

        if not beats:
            raise RuntimeError("Story blueprint provider returned no usable beats.")

        return StoryBlueprint(
            topic=normalized_topic,
            genre_id=editorial_profile.genre_id,
            target_duration_seconds=target_duration_seconds,
            beats=beats,
            prompt_version=request.prompt_version,
            research_id=research.id if research is not None else None,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        editorial_profile: EditorialProfile,
        target_duration_seconds: int,
        story_angle: StoryAngle,
        audience_promise: AudiencePromise,
        facts: list[ResearchFact],
        additional_instructions: str | None,
    ) -> str:
        available_types = ", ".join(beat_type.value for beat_type in StoryBeatType)
        content_intelligence = editorial_profile.content_intelligence

        architecture_hint = (
            f"Narrative architecture guidance for this genre: "
            f"{content_intelligence.narrative_architecture_hint}\n"
            if content_intelligence.narrative_architecture_hint
            else ""
        )

        pacing_curve_lines = "\n".join(
            f"  {segment.progress_start:.0%}-{segment.progress_end:.0%}: "
            f"tension {segment.tension_level}, "
            f"reveal probability {segment.reveal_probability}"
            for segment in content_intelligence.pacing_curve
        )
        pacing_hint = (
            f"Target tension/reveal curve across runtime:\n{pacing_curve_lines}\n"
            if pacing_curve_lines
            else ""
        )

        facts_section = ""

        if facts:
            fact_lines = "\n".join(
                f"FACT_{index}: {fact.text}"
                for index, fact in enumerate(facts, start=1)
            )
            facts_section = (
                f"\nVerified facts available to draw on:\n{fact_lines}\n"
                "For each beat, if it relies on any of these facts, add "
                "a line EVIDENCE_FACT_IDS: <comma-separated fact "
                "numbers, or 'none'>.\n"
            )

        instructions_section = (
            f"\nAdditional instruction: {additional_instructions}\n"
            if additional_instructions
            else ""
        )

        return (
            f"Topic: {topic}\n"
            f"Genre: {editorial_profile.genre_id}\n"
            f"Target duration: {target_duration_seconds} seconds\n"
            f"Selected angle [{story_angle.style.value}]: {story_angle.title} - "
            f"{story_angle.description}\n"
            f"Expected payoff: {audience_promise.expected_payoff}\n"
            f"{architecture_hint}"
            f"{pacing_hint}"
            f"{facts_section}"
            f"{instructions_section}\n"
            f"Design a beat-by-beat structure covering the full "
            f"{target_duration_seconds} seconds. Available beat "
            f"types: {available_types}. Use only the beats that fit "
            "this genre, duration, and story - do not force every "
            "type in, and do not reuse a fixed template.\n\n"
            "Return one block per beat, in chronological order, "
            "separated by a line of three or more dashes:\n"
            "BEAT_TYPE: <one type from the available list>\n"
            "START: <seconds from 0>\n"
            "END: <seconds, greater than START>\n"
            "PURPOSE: <what this beat accomplishes>\n"
            "TENSION: <0-100, vary this across beats rather than "
            "keeping it constant>"
        )

    @classmethod
    def _parse_beats(
        cls, content: str, *, facts: list[ResearchFact]
    ) -> list[StoryBeat]:
        beats: list[StoryBeat] = []

        for block in split_blocks(content):
            beat_type_raw = extract_labeled_field(block, "BEAT_TYPE")
            start_raw = extract_labeled_field(block, "START")
            end_raw = extract_labeled_field(block, "END")
            purpose = extract_labeled_field(block, "PURPOSE")
            tension_raw = extract_labeled_field(block, "TENSION")

            if not (
                beat_type_raw and start_raw and end_raw and purpose and tension_raw
            ):
                continue

            normalized_type = beat_type_raw.strip().lower()

            if normalized_type not in _VALID_BEAT_TYPES:
                continue

            start = cls._parse_number(start_raw)
            end = cls._parse_number(end_raw)
            tension = cls._parse_number(tension_raw)

            if start is None or end is None or tension is None:
                continue

            evidence_fact_ids = cls._parse_evidence_fact_ids(block, facts=facts)

            try:
                beats.append(
                    StoryBeat(
                        beat_type=StoryBeatType(normalized_type),
                        start_seconds=start,
                        end_seconds=end,
                        purpose=purpose,
                        tension_level=int(tension),
                        evidence_fact_ids=evidence_fact_ids,
                    )
                )
            except ValueError:
                continue

        return beats

    @staticmethod
    def _parse_evidence_fact_ids(
        block: str, *, facts: list[ResearchFact]
    ) -> list[UUID]:
        if not facts:
            return []

        raw = extract_labeled_field(block, "EVIDENCE_FACT_IDS")

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

    @staticmethod
    def _parse_number(raw: str) -> float | None:
        try:
            return float(raw.strip())
        except ValueError:
            return None
