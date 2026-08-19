from __future__ import annotations

from collections import defaultdict

from src.models.editorial_critique import CriticFinding, EditorialCritique
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class ScriptRevisionService:
    """
    Revises a generated script's narration to address one
    EditorialCritique's findings - and only those findings. Segment
    count, timing, and structural role are carried over unchanged from
    the input script, the same discipline NarrativeCompressionService
    follows: this service was not told to redecide structure, so it
    doesn't. A segment with no finding against it, and no general
    (script-wide) finding requiring a change, comes back unchanged.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated script revision cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def revise(
        self,
        *,
        script: GeneratedScript,
        critique: EditorialCritique,
    ) -> GeneratedScript:
        if not critique.findings:
            raise ValueError(
                "Script revision requires at least one critique finding to " "act on."
            )

        ordered_segments = sorted(
            script.segments, key=lambda segment: segment.start_seconds
        )
        findings_by_segment = self._group_findings(critique.findings)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                ordered_segments=ordered_segments,
                findings_by_segment=findings_by_segment,
            ),
            system_prompt=(
                "You are an expert script editor performing a targeted "
                "revision. Only change a segment's narration if a "
                "finding below applies to it - either a finding tied "
                "to its exact segment number, or a general finding "
                "that genuinely requires a change there. Leave every "
                "other segment's narration completely unchanged. Do "
                "not restructure, reorder, merge, or split segments."
            ),
            prompt_version="script_revision_prompt_v1.0.0",
            dry_run_response="\n---\n".join(
                self._dry_run_block(segment.segment_number, segment.narration)
                for segment in ordered_segments
            ),
            metadata={
                "agent": "ScriptRevisionService",
                "workflow": "script_revision",
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

            raise RuntimeError(f"Script revision failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Script revision provider returned empty content.")

        revised_by_number = self._parse_revised_narration(content)

        updated_segments = [
            (
                segment.model_copy(
                    update={"narration": revised_by_number[segment.segment_number]}
                )
                if segment.segment_number in revised_by_number
                else segment
            )
            for segment in script.segments
        ]

        return script.model_copy(update={"segments": updated_segments})

    @staticmethod
    def _group_findings(
        findings: list[CriticFinding],
    ) -> dict[int | None, list[CriticFinding]]:
        grouped: dict[int | None, list[CriticFinding]] = defaultdict(list)

        for finding in findings:
            grouped[finding.segment_number].append(finding)

        return grouped

    @staticmethod
    def _build_prompt(
        *,
        ordered_segments: list[ScriptSegment],
        findings_by_segment: dict[int | None, list[CriticFinding]],
    ) -> str:
        segment_lines = []

        for segment in ordered_segments:
            findings = findings_by_segment.get(segment.segment_number, [])
            findings_text = (
                "; ".join(
                    f"[{finding.severity.value}] {finding.problem} -> "
                    f"{finding.recommended_correction}"
                    for finding in findings
                )
                if findings
                else "no findings"
            )

            segment_lines.append(
                f"SEGMENT {segment.segment_number} (findings: {findings_text}): "
                f"{segment.narration}"
            )

        general_findings = findings_by_segment.get(None, [])
        general_text = (
            "\n".join(
                f"- [{finding.severity.value}] {finding.problem} -> "
                f"{finding.recommended_correction}"
                for finding in general_findings
            )
            if general_findings
            else "none"
        )

        return (
            "Script segments, each annotated with the findings that "
            "apply to it:\n" + "\n".join(segment_lines) + "\n\n"
            f"General findings affecting the whole script:\n{general_text}\n\n"
            "Return one block per segment, separated by a line of "
            "three or more dashes:\n"
            "SEGMENT: <the segment number above>\n"
            "NARRATION: <the revised narration, or the original "
            "narration unchanged if no finding applies>"
        )

    @staticmethod
    def _dry_run_block(segment_number: int, narration: str) -> str:
        return f"SEGMENT: {segment_number}\nNARRATION: {narration}"

    @staticmethod
    def _parse_revised_narration(content: str) -> dict[int, str]:
        revised: dict[int, str] = {}

        for block in split_blocks(content):
            segment_raw = extract_labeled_field(block, "SEGMENT")
            narration = extract_labeled_field(block, "NARRATION")

            if not (segment_raw and narration):
                continue

            try:
                segment_number = int(segment_raw.strip())
            except ValueError:
                continue

            revised[segment_number] = narration

        return revised
