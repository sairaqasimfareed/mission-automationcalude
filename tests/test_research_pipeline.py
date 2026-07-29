from src.models.research import ResearchStatus
from src.services.research_pipeline import ResearchPipeline


pipeline = ResearchPipeline()

result = pipeline.run(
    "Top 10 Hidden Underground Cities"
)

print("Topic:", result.topic)
print("Final status:", result.status)
print("Review notes:", result.claude_review_notes)
print("Suggested changes:", result.claude_suggested_changes)

assert result.status == ResearchStatus.APPROVED
assert len(result.claude_review_notes) > 0

print("Research pipeline test completed successfully.")