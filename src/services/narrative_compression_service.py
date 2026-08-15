from __future__ import annotations

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class NarrativeCompressionService:
    """
    Removes filler, redundant exposition, and generic AI language from
    an already-generated script's narration (spec section 35).

    Only narration text changes - segment count, timing, structural
    role, and tension are carried over unchanged from the input
    script, the same "never redecide upstream structure" discipline
    ScriptGenerationService follows. Compression is targeted, not
    blind shortening: a segment the LLM finds nothing to cut in comes
    back with its narration unchanged.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated narrative compression cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def compress(self, script: GeneratedScript) -> GeneratedScript:
        """Return a copy of script with compressed narration per segment."""

        ordered_segments = sorted(
            script.segments, key=lambda segment: segment.start_seconds
        )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(ordered_segments),
            system_prompt=(
                "You are an expert script editor specializing in "
                "narrative compression. For each segment, remove "
                "filler, repeated facts, redundant exposition, "
                "unnecessary adjectives, repetitive transitions, "
                "generic AI language, empty dramatic statements, and "
                "overexplaining. Do not shorten a segment that "
                "already has no unnecessary material - return it "
                "unchanged. Never remove information the narration "
                "depends on to make sense."
            ),
            prompt_version="narrative_compression_prompt_v1.0.0",
            dry_run_response="\n---\n".join(
                self._dry_run_block(segment.segment_number, segment.narration)
                for segment in ordered_segments
            ),
            metadata={
                "agent": "NarrativeCompressionService",
                "workflow": "narrative_compression",
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

            raise RuntimeError(f"Narrative compression failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Narrative compression provider returned empty content.")

        compressed_by_number = self._parse_compressed_narration(content)

        updated_segments = [
            (
                segment.model_copy(
                    update={"narration": compressed_by_number[segment.segment_number]}
                )
                if segment.segment_number in compressed_by_number
                else segment
            )
            for segment in script.segments
        ]

        return script.model_copy(update={"segments": updated_segments})

    @staticmethod
    def _build_prompt(ordered_segments: list[ScriptSegment]) -> str:
        segment_lines = "\n".join(
            f"SEGMENT {segment.segment_number}: {segment.narration}"
            for segment in ordered_segments
        )

        return (
            f"Compress the narration below, segment by segment:\n\n"
            f"{segment_lines}\n\n"
            "Return one block per segment, separated by a line of "
            "three or more dashes:\n"
            "SEGMENT: <the segment number above>\n"
            "NARRATION: <the compressed narration for this segment>"
        )

    @staticmethod
    def _dry_run_block(segment_number: int, narration: str) -> str:
        return f"SEGMENT: {segment_number}\nNARRATION: {narration}"

    @staticmethod
    def _parse_compressed_narration(content: str) -> dict[int, str]:
        compressed: dict[int, str] = {}

        for block in split_blocks(content):
            segment_raw = extract_labeled_field(block, "SEGMENT")
            narration = extract_labeled_field(block, "NARRATION")

            if not (segment_raw and narration):
                continue

            try:
                segment_number = int(segment_raw.strip())
            except ValueError:
                continue

            compressed[segment_number] = narration

        return compressed
