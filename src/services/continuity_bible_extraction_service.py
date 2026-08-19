from __future__ import annotations

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityEntryType,
)
from src.models.generated_script import GeneratedScript
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_REQUIRED_LABELS = ("TYPE", "NAME", "DESCRIPTION", "SEGMENT")
_VALID_TYPES = {entry_type.value for entry_type in ContinuityEntryType}

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        (
            "TYPE: character\n"
            "NAME: Dry-run character\n"
            "DESCRIPTION: Dry-run character description for development "
            "and testing purposes only.\n"
            "SEGMENT: 1"
        ),
        (
            "TYPE: location\n"
            "NAME: Dry-run location\n"
            "DESCRIPTION: Dry-run location description for development "
            "and testing purposes only.\n"
            "SEGMENT: 1"
        ),
    ]
)


class ContinuityBibleExtractionService:
    """
    Extracts every character, location, timeline point, and
    standalone fact a script establishes, in one batched LLM call -
    the same "writing and evaluation are separate passes" discipline
    as every other extraction/evaluation service in this engine.
    Reading free narration for named entities and facts genuinely
    needs an LLM; there is no honest mechanical shortcut for this
    part (see ContinuityValidationService for the rule-based check
    that runs on the result).
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated continuity bible extraction cost cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def extract(self, script: GeneratedScript) -> ContinuityBible:
        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(script),
            system_prompt=(
                "You are a continuity supervisor for a video script, "
                "the same role a TV writers' room continuity editor "
                "plays. Read the full script and extract every "
                "character, location, timeline point, and standalone "
                "fact it establishes, exactly as stated - do not "
                "invent detail the script does not contain."
            ),
            prompt_version="continuity_bible_extraction_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "ContinuityBibleExtractionService",
                "workflow": "continuity_bible_extraction",
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

            raise RuntimeError(f"Continuity bible extraction failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError(
                "Continuity bible extraction provider returned empty content."
            )

        entries = self._parse_entries(content)

        return ContinuityBible(
            topic=script.topic,
            entries=entries,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(script: GeneratedScript) -> str:
        ordered_segments = sorted(
            script.segments, key=lambda segment: segment.start_seconds
        )
        segment_lines = "\n".join(
            f"SEGMENT {segment.segment_number}: {segment.narration}"
            for segment in ordered_segments
        )

        return (
            f"Topic: {script.topic}\n\n"
            f"Script segments:\n{segment_lines}\n\n"
            "Extract every character, location, timeline point, and "
            "standalone fact this script establishes. Return one "
            "block per entry, separated by a line of three or more "
            "dashes, with exactly these labeled lines:\n"
            "TYPE: <one of: character, location, timeline, fact>\n"
            "NAME: <a short canonical name for this entry>\n"
            "DESCRIPTION: <what the script establishes about it, in "
            "your own words>\n"
            "SEGMENT: <the segment number where it is first mentioned>\n\n"
            "If the same character, location, or fact is mentioned "
            "again in a later segment, do not repeat it as a new "
            "entry unless it adds new detail - in that case, return "
            "a second entry with the same NAME so both mentions can "
            "be compared."
        )

    @staticmethod
    def _parse_entries(content: str) -> list[ContinuityEntry]:
        entries: list[ContinuityEntry] = []

        for block in split_blocks(content):
            fields = {
                label: extract_labeled_field(block, label) for label in _REQUIRED_LABELS
            }

            if any(fields[label] is None for label in _REQUIRED_LABELS):
                continue

            entry_type_raw = (fields["TYPE"] or "").strip().lower()

            if entry_type_raw not in _VALID_TYPES:
                continue

            segment_raw = (fields["SEGMENT"] or "").strip()

            try:
                segment_number = int(segment_raw)
            except ValueError:
                continue

            if segment_number < 1:
                continue

            entries.append(
                ContinuityEntry(
                    entry_type=ContinuityEntryType(entry_type_raw),
                    name=fields["NAME"] or "",
                    description=fields["DESCRIPTION"] or "",
                    first_mentioned_segment=segment_number,
                )
            )

        return entries
