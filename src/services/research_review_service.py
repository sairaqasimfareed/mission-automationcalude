from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchStatus,
)


class ResearchReviewService:
    """
    Reviews research before it is passed to the Script Agent.

    Dry-run version.
    Claude API integration will replace this later.
    """

    def review(
        self,
        research: ResearchResult,
    ) -> ResearchResult:

        if len(research.key_facts) < 2:

            research.status = ResearchStatus.REVISION_REQUIRED

            research.claude_review_notes.append(
                "Research contains too few verified facts."
            )

            research.claude_suggested_changes.append(
                "Add more high-confidence facts."
            )

            return research

        research.status = ResearchStatus.APPROVED

        research.claude_review_notes.append(
            "Research passed the quality review."
        )

        return research