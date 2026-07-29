from datetime import UTC, datetime

from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)

script = Script(
    title="Top 10 Hidden Underground Cities",
    content="This is a draft script for testing.",
    prompt_version="script_prompt_v1.0.0",
)

print("Title:", script.title)
print("Prompt version:", script.prompt_version)
print("Status:", script.status)
print("Claude review:", script.claude_review_status)


script.status = ScriptStatus.UNDER_REVIEW
script.claude_review_status = ScriptReviewStatus.REVISION_REQUIRED
script.claude_review_notes = [
    "The opening hook is too generic.",
    "Scene three repeats an earlier point.",
]
script.claude_suggested_changes = [
    "Replace the opening with a stronger curiosity gap.",
    "Add original analysis in scene three.",
]
script.claude_reviewed_at = datetime.now(UTC)
script.revision_count += 1

print("Updated status:", script.status)
print("Updated Claude review:", script.claude_review_status)
print("Revision count:", script.revision_count)
print("Script model tests completed successfully.")
