from src.models.research import ResearchResult, ResearchStatus
from src.models.script import ScriptReviewStatus, ScriptStatus
from src.services.script_pipeline import ScriptPipeline


research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "Underground cities were built for protection, survival, and trade."
    ),
    key_facts=[
        "Several underground cities contain homes and storage rooms.",
        "Many were designed to protect communities from invasion.",
    ],
    prompt_version="research_prompt_v1.0.0",
    status=ResearchStatus.APPROVED,
)

pipeline = ScriptPipeline()
script = pipeline.run(research)

print("Title:", script.title)
print("Final status:", script.status)
print("Claude review:", script.claude_review_status)
print("Review notes:", script.claude_review_notes)
print("Revision count:", script.revision_count)

assert script.status == ScriptStatus.APPROVED
assert script.claude_review_status == ScriptReviewStatus.APPROVED
assert len(script.claude_review_notes) > 0

print("Script pipeline test completed successfully.")