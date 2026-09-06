from __future__ import annotations

from src.models.continuity_bible import ContinuityBible
from src.models.generated_script import GeneratedScript
from src.models.production_ambiguity import (
    AmbiguityResolutionStatus,
    ProductionAmbiguity,
)
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class ProductionAmbiguityService:
    """
    Content Studio Redesign, Phase 16: "Unknown continuity-critical
    choices become ambiguities rather than silent permanent
    inventions." Primary performs the extraction; nothing here ever
    silently decides an ambiguity on its own - resolve_by_ai() is
    still a distinct, explicit, logged action a person triggers, not
    an automatic default.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated production ambiguity cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def detect(
        self,
        *,
        script: GeneratedScript,
        continuity_bible: ContinuityBible | None,
    ) -> list[ProductionAmbiguity]:
        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_detect_prompt(
                script=script, continuity_bible=continuity_bible
            ),
            system_prompt=(
                "You are identifying production-relevant questions this "
                "script's text does not settle - never invent an answer, "
                "only flag what is genuinely ambiguous. Mark an "
                "ambiguity continuity-critical only when leaving it "
                "unresolved would create a visible inconsistency in the "
                "finished video."
            ),
            prompt_version="production_ambiguity_detection_prompt_v1.0.0",
            dry_run_response=(
                "DESCRIPTION: The exact time period is not stated.\n"
                "SEGMENT_NUMBER: none\n"
                "CONTINUITY_CRITICAL: no"
            ),
            metadata={
                "agent": "ProductionAmbiguityService",
                "workflow": "production_ambiguity_detection",
                "topic": script.topic,
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

            raise RuntimeError(
                f"Production ambiguity detection failed: {error_message}"
            )

        content = (service_result.result.content or "").strip()

        return self._parse_ambiguities(content)

    def resolve_by_ai(
        self,
        *,
        ambiguity: ProductionAmbiguity,
        script: GeneratedScript,
    ) -> ProductionAmbiguity:
        if ambiguity.status != AmbiguityResolutionStatus.UNRESOLVED:
            raise ValueError("This ambiguity is already resolved.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=(
                f"Script topic: {script.topic}\n"
                f"Ambiguity: {ambiguity.description}\n\n"
                "Propose one reasonable, specific resolution a production "
                "team could act on. Return exactly:\n"
                "DECISION: <the resolution, one or two sentences>"
            ),
            system_prompt=(
                "You are making one production decision on an ambiguity "
                "nobody has resolved yet. Be concrete and specific, not "
                "vague."
            ),
            prompt_version="production_ambiguity_resolution_prompt_v1.0.0",
            dry_run_response="DECISION: Treat this as a contemporary setting unless later evidence contradicts it.",
            metadata={
                "agent": "ProductionAmbiguityService",
                "workflow": "production_ambiguity_resolution",
                "topic": script.topic,
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

            raise RuntimeError(
                f"Production ambiguity resolution failed: {error_message}"
            )

        content = (service_result.result.content or "").strip()
        decision = extract_labeled_field(content, "DECISION")

        if not decision or not decision.strip():
            raise RuntimeError(
                "Production ambiguity resolution provider returned no decision."
            )

        return ambiguity.model_copy(
            update={
                "status": AmbiguityResolutionStatus.RESOLVED_BY_AI,
                "resolution_note": decision.strip(),
            }
        )

    @staticmethod
    def resolve_manually(
        *, ambiguity: ProductionAmbiguity, note: str
    ) -> ProductionAmbiguity:
        if ambiguity.status != AmbiguityResolutionStatus.UNRESOLVED:
            raise ValueError("This ambiguity is already resolved.")

        cleaned_note = note.strip()

        if not cleaned_note:
            raise ValueError("Resolving an ambiguity manually requires a note.")

        return ambiguity.model_copy(
            update={
                "status": AmbiguityResolutionStatus.RESOLVED_MANUALLY,
                "resolution_note": cleaned_note,
            }
        )

    @staticmethod
    def _build_detect_prompt(
        *,
        script: GeneratedScript,
        continuity_bible: ContinuityBible | None,
    ) -> str:
        bible_section = ""

        if continuity_bible is not None and continuity_bible.entries:
            entry_lines = "\n".join(
                f"- [{entry.entry_type.value}] {entry.name}: {entry.description}"
                for entry in continuity_bible.entries
            )
            bible_section = f"Already-established facts:\n{entry_lines}\n\n"

        return (
            f"Script narration:\n{script.full_narration}\n\n"
            f"{bible_section}"
            "Identify production-relevant ambiguities this script does "
            "not settle (e.g. unclear time period, an undescribed "
            "character's appearance, a segment with no clear visual "
            "direction). Return one block per ambiguity, separated by "
            "a line of three or more dashes:\n"
            "DESCRIPTION: <the ambiguity, one sentence>\n"
            "SEGMENT_NUMBER: <the segment number it applies to, or "
            "'none' for a whole-script ambiguity>\n"
            "CONTINUITY_CRITICAL: <yes or no - would leaving this "
            "unresolved create a visible inconsistency in the finished "
            "video>\n\n"
            "If there are no genuine ambiguities, return nothing."
        )

    @staticmethod
    def _parse_ambiguities(content: str) -> list[ProductionAmbiguity]:
        ambiguities: list[ProductionAmbiguity] = []

        for block in split_blocks(content):
            description = extract_labeled_field(block, "DESCRIPTION")

            if not description:
                continue

            segment_raw = extract_labeled_field(block, "SEGMENT_NUMBER")
            segment_number = None

            if segment_raw and segment_raw.strip().lower() != "none":
                try:
                    segment_number = int(segment_raw.strip())
                except ValueError:
                    segment_number = None

            critical_raw = extract_labeled_field(block, "CONTINUITY_CRITICAL")
            continuity_critical = bool(
                critical_raw and critical_raw.strip().lower() == "yes"
            )

            try:
                ambiguities.append(
                    ProductionAmbiguity(
                        description=description,
                        segment_number=segment_number,
                        continuity_critical=continuity_critical,
                    )
                )
            except ValueError:
                continue

        return ambiguities
