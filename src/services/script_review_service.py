from __future__ import annotations

from datetime import UTC, datetime

from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)


class ScriptReviewService:
    """Reviews a generated script before it can move to production."""

    def review(self, script: Script) -> Script:
        """
        Dry-run Claude-style script review.

        A real Anthropic API review will replace this rule-based
        implementation later.
        """

        if script.word_count < 15:
            script.status = ScriptStatus.REVISION_REQUIRED
            script.claude_review_status = (
                ScriptReviewStatus.REVISION_REQUIRED
            )
            script.claude_review_notes.append(
                "The script is too short for production."
            )
            script.claude_suggested_changes.append(
                "Expand the script with more detail and original analysis."
            )
            script.claude_reviewed_at = datetime.now(UTC)
            script.revision_count += 1
            return script

        script.status = ScriptStatus.APPROVED
        script.claude_review_status = ScriptReviewStatus.APPROVED
        script.claude_review_notes.append(
            "The script passed the dry-run Claude review."
        )
        script.claude_reviewed_at = datetime.now(UTC)

        return script