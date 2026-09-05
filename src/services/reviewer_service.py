from __future__ import annotations

from src.models.artifact_lifecycle import ArtifactType
from src.models.editorial_critique import FindingSeverity
from src.models.reviewer_result import ReviewerIssue, ReviewerResult
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_ISSUE_LABELS = ("DESCRIPTION", "SEVERITY", "RECOMMENDATION")
_VALID_SEVERITIES = {severity.value for severity in FindingSeverity}
_PROMPT_VERSION = "reviewer_service_prompt_v1.0.0"

# Content Studio Redesign, Phase 8: research-specific review focus,
# additive to the generic prompt below - "Reviewer findings highlight
# unsupported claims, weak sources, contradictions, unanswered
# questions and missing perspectives." No other artifact type gets
# special-cased guidance; this stays a plain dict lookup so adding a
# future artifact-specific focus never touches the parsing contract.
_ARTIFACT_FOCUS_GUIDANCE: dict[ArtifactType, str] = {
    ArtifactType.RESEARCH: (
        "Pay particular attention to: unsupported claims (asserted "
        "without a cited source), weak or low-credibility sources, "
        "unresolved contradictions between sources, research questions "
        "left unanswered, and missing perspectives or counter-evidence."
    ),
    ArtifactType.STORY_ARCHITECTURE: (
        "Pay particular attention to: pacing, use of the available "
        "evidence, premature reveals, weak escalation, missing "
        "payoffs, duration mismatch against the target runtime, and "
        "redundant beats."
    ),
}


class ReviewerService:
    """
    The generic "Reviewer LLM" role (Content Studio Redesign, Phase 4):
    critiques any artifact type on demand, using the same batched-call,
    labeled-block-parsing discipline EditorialCritiqueService already
    established for scripts specifically - generalized here so Topic,
    Audience, Research, Story, and Hook can all be reviewed the same
    way, without inventing a parallel critique mechanism per artifact
    type.

    The Reviewer never authors an alternative - review() returns
    strengths/issues/a suggested *direction*, never rewritten content.
    Applying a suggestion is always a separate action that goes through
    Primary (ScriptRevisionService or an equivalent for other artifact
    types), matching "Reviewer reviews Primary output... it does not
    independently become the author."

    reviewer_profile_id being None is a real, fully supported case -
    no reviewer configured for this project - and review() returns
    None immediately without making any LLM call, rather than raising.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated reviewer cost cannot be negative.")

        self.llm_service = llm_service
        self.estimated_cost_usd = estimated_cost_usd

    def review(
        self,
        *,
        artifact_type: ArtifactType,
        content: str,
        context: str,
        reviewer_profile_id: str | None,
    ) -> ReviewerResult | None:
        if reviewer_profile_id is None:
            return None

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                artifact_type=artifact_type, content=content, context=context
            ),
            system_prompt=(
                "You are an independent reviewer evaluating one "
                f"{artifact_type.value} artifact. You did not create "
                "this artifact - judge it honestly. You critique; you "
                "never rewrite it yourself."
            ),
            prompt_version=_PROMPT_VERSION,
            dry_run_response=self._dry_run_response(),
            metadata={
                "agent": "ReviewerService",
                "workflow": "reviewer_result",
                "artifact_type": artifact_type.value,
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=[reviewer_profile_id],
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(f"Reviewer pass failed: {error_message}")

        response_content = (service_result.result.content or "").strip()

        if not response_content:
            raise RuntimeError("Reviewer provider returned empty content.")

        blocks = split_blocks(response_content)

        if not blocks:
            raise RuntimeError("Reviewer provider returned no usable output.")

        strengths = self._parse_strengths(blocks[0])
        issues: list[ReviewerIssue] = []
        suggested_revision_direction: str | None = None

        for block in blocks[1:]:
            direction = extract_labeled_field(block, "SUGGESTED_REVISION_DIRECTION")

            if direction is not None:
                suggested_revision_direction = direction.strip() or None

                continue

            issue = self._parse_issue(block)

            if issue is not None:
                issues.append(issue)

        return ReviewerResult(
            artifact_type=artifact_type,
            reviewer_profile_id=reviewer_profile_id,
            prompt_version=_PROMPT_VERSION,
            strengths=strengths,
            issues=issues,
            suggested_revision_direction=suggested_revision_direction,
        )

    @staticmethod
    def _build_prompt(
        *, artifact_type: ArtifactType, content: str, context: str
    ) -> str:
        valid_severities = ", ".join(sorted(_VALID_SEVERITIES))
        focus_guidance = _ARTIFACT_FOCUS_GUIDANCE.get(artifact_type)
        focus_section = f"{focus_guidance}\n\n" if focus_guidance else ""

        return (
            f"Artifact type: {artifact_type.value}\n\n"
            f"Context (upstream approved material, project settings):\n"
            f"{context}\n\n"
            f"Artifact content to review:\n{content}\n\n"
            f"{focus_section}"
            "First, return exactly one block with one line per genuine "
            "strength you find:\n"
            "STRENGTH: <what is good about this, specifically>\n\n"
            "Then, separated by a line of three or more dashes, return "
            "one block per real issue you find, with exactly these "
            "labeled lines:\n"
            "DESCRIPTION: <what is wrong, specifically>\n"
            f"SEVERITY: <one of: {valid_severities}>\n"
            "RECOMMENDATION: <a specific, actionable fix, or 'none'>\n\n"
            "If you find no issues at all, return only the strengths "
            "block. Optionally end with one final block containing only:\n"
            "SUGGESTED_REVISION_DIRECTION: <a short description of the "
            "overall direction a revision should take, or omit this "
            "block entirely if no revision is needed>"
        )

    @staticmethod
    def _dry_run_response() -> str:
        return "STRENGTH: The core idea is clear and well-supported."

    @staticmethod
    def _parse_strengths(block: str) -> list[str]:
        strengths: list[str] = []

        for line in block.splitlines():
            value = extract_labeled_field(line, "STRENGTH")

            if value is not None and value.strip():
                strengths.append(value.strip())

        return strengths

    @staticmethod
    def _parse_issue(block: str) -> ReviewerIssue | None:
        fields = {label: extract_labeled_field(block, label) for label in _ISSUE_LABELS}

        if fields["DESCRIPTION"] is None or fields["SEVERITY"] is None:
            return None

        severity_raw = (fields["SEVERITY"] or "").strip().lower()

        if severity_raw not in _VALID_SEVERITIES:
            return None

        recommendation_raw = (fields["RECOMMENDATION"] or "").strip()
        recommendation = (
            None
            if not recommendation_raw or recommendation_raw.lower() == "none"
            else recommendation_raw
        )

        return ReviewerIssue(
            description=fields["DESCRIPTION"] or "",
            severity=FindingSeverity(severity_raw),
            recommendation=recommendation,
        )
