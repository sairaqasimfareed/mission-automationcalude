from __future__ import annotations

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_selection_edit import (
    SelectionEditOperation,
    SelectionEditRequest,
)
from src.models.writing_directives import WritingDirectiveSet
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_OPERATION_INSTRUCTIONS = {
    SelectionEditOperation.REWRITE: (
        "Rewrite the target text with fresh wording while preserving "
        "its meaning and every factual claim."
    ),
    SelectionEditOperation.SHORTEN: (
        "Make the target text more concise without losing its meaning "
        "or any factual claim."
    ),
    SelectionEditOperation.EXPAND: (
        "Expand the target text with more detail or texture, without "
        "introducing any new factual claim the surrounding context "
        "does not already support."
    ),
    SelectionEditOperation.MORE_SUSPENSEFUL: (
        "Rewrite the target text to build more suspense and tension."
    ),
    SelectionEditOperation.MORE_NATURAL: (
        "Rewrite the target text so it sounds more natural when spoken " "aloud."
    ),
    SelectionEditOperation.IMPROVE_TRANSITION: (
        "Rewrite the target text so it transitions more smoothly from "
        "what comes immediately before it."
    ),
}


class ScriptSelectionEditService:
    """
    Applies one selection-scoped AI edit to a single script segment
    (Content Studio Redesign, Phase 12).

    This is a distinct, narrower path from ScriptRevisionService: that
    service applies a whole EditorialCritique's findings, potentially
    across many segments; this service applies one person-chosen
    operation to one segment (or a substring within it) on demand,
    with no critique involved - "Primary writes/revises, Reviewer
    critiques, Reviewer never directly overwrites" holds here exactly
    as it does for ScriptGenerationService/ScriptRevisionService: this
    is a Primary-side write path a person triggers directly, not the
    Reviewer.

    Every other segment is returned byte-identical, and the edited
    segment's timing/narrative_function/source_claim_references are
    never changed - only its narration text - matching the same
    "never redecide structure it wasn't told to change" discipline
    every other script-touching service in this codebase follows. This
    is what "hook preservation" and "evidence-grounding" mean in
    practice here: editing segment N can never silently alter segment
    M's hook narration, upstream selected_hook, or any segment's
    already-bound source_claim_references.

    The "context envelope": the LLM sees the immediately preceding and
    following segments' narration as read-only context (so a
    transition edit, or a rewrite, still reads coherently in place),
    but only the target segment's narration is ever returned/applied.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated selection edit cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def edit(
        self,
        *,
        script: GeneratedScript,
        request: SelectionEditRequest,
        writing_directives: WritingDirectiveSet | None = None,
    ) -> tuple[GeneratedScript, str]:
        """
        Apply one selection edit, returning the revised script and a
        human-readable change summary (for ScriptVersionService).
        """

        ordered = sorted(script.segments, key=lambda segment: segment.segment_number)
        by_number = {segment.segment_number: segment for segment in ordered}

        target = by_number.get(request.segment_number)

        if target is None:
            raise ValueError(f"Script has no segment {request.segment_number}.")

        if (
            request.selected_text is not None
            and request.selected_text not in target.narration
        ):
            raise ValueError(
                "selected_text must be an exact substring of the target "
                "segment's narration."
            )

        index = ordered.index(target)
        previous_segment = ordered[index - 1] if index > 0 else None
        next_segment = ordered[index + 1] if index + 1 < len(ordered) else None

        llm_request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                target=target,
                previous_segment=previous_segment,
                next_segment=next_segment,
                request=request,
                writing_directives=writing_directives,
            ),
            system_prompt=(
                "You are editing one segment of an existing video "
                "script narration on a person's direct instruction. "
                "Change only the requested text. Never state a claim "
                "the surrounding context does not support. Never "
                "change what happens structurally - only the wording."
            ),
            prompt_version="script_selection_edit_prompt_v1.0.0",
            dry_run_response=(
                "NARRATION: Dry-run edited narration for segment "
                f"{target.segment_number}."
            ),
            metadata={
                "agent": "ScriptSelectionEditService",
                "workflow": "script_selection_edit",
                "operation": request.operation.value,
            },
        )

        service_result = self.llm_service.generate(
            llm_request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(f"Script selection edit failed: {error_message}")

        content = (service_result.result.content or "").strip()
        new_text = extract_labeled_field(content, "NARRATION")

        if not new_text or not new_text.strip():
            raise RuntimeError("Script selection edit provider returned no narration.")

        new_text = new_text.strip()

        if request.selected_text is not None:
            new_narration = target.narration.replace(request.selected_text, new_text, 1)
        else:
            new_narration = new_text

        revised_target = target.model_copy(update={"narration": new_narration})

        revised_segments = [
            (
                revised_target
                if segment.segment_number == target.segment_number
                else segment
            )
            for segment in script.segments
        ]

        revised_script = script.model_copy(update={"segments": revised_segments})

        return revised_script, self._change_summary(request)

    @staticmethod
    def _change_summary(request: SelectionEditRequest) -> str:
        if request.operation == SelectionEditOperation.CUSTOM:
            return (
                f"Segment {request.segment_number}: custom edit - "
                f"{request.custom_instruction}"
            )

        return (
            f"Segment {request.segment_number}: "
            f"{request.operation.value.replace('_', ' ')}."
        )

    @staticmethod
    def _build_prompt(
        *,
        target: ScriptSegment,
        previous_segment: ScriptSegment | None,
        next_segment: ScriptSegment | None,
        request: SelectionEditRequest,
        writing_directives: WritingDirectiveSet | None,
    ) -> str:
        context_lines = []

        if previous_segment is not None:
            context_lines.append(
                "Previous segment (context only, do not change): "
                f"{previous_segment.narration}"
            )

        context_lines.append(
            f"Target segment (segment {target.segment_number}): " f"{target.narration}"
        )

        if next_segment is not None:
            context_lines.append(
                "Next segment (context only, do not change): "
                f"{next_segment.narration}"
            )

        context_block = "\n".join(context_lines)

        instruction = (
            request.custom_instruction
            if request.operation == SelectionEditOperation.CUSTOM
            else _OPERATION_INSTRUCTIONS[request.operation]
        )

        directives_section = ""

        if writing_directives is not None:
            directive_lines = "\n".join(
                f"- {directive.text}" for directive in writing_directives.directives
            )
            directives_section = (
                f"Writing directives (must follow):\n{directive_lines}\n\n"
            )

        selection_line = (
            f'Selected text to change: "{request.selected_text}"\n'
            if request.selected_text is not None
            else "No specific selection - edit the full target segment.\n"
        )

        return (
            f"{context_block}\n\n"
            f"{directives_section}"
            f"{selection_line}"
            f"Instruction: {instruction}\n\n"
            "Return only the revised text for the target segment (or, "
            "if a selection was given, only the revised replacement "
            "for exactly that selected text) as:\n"
            "NARRATION: <revised text>"
        )
