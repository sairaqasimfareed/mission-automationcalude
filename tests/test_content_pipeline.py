from src.models.enums import (
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.video_job import VideoJob
from src.services.content_pipeline import ContentPipeline


job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery and Hidden Places",
    topic="Top 10 Hidden Underground Cities",
    platform=Platform.YOUTUBE,
    production_mode=ProductionMode.PREMIUM,
)

pipeline = ContentPipeline()

result = pipeline.run(job)

print("Project:", result.project_name)
print("Topic:", result.topic)
print("Current Stage:", result.current_stage)

print()

print("Research Status:", result.research.status)
print("Script Status:", result.script.status)
print("Originality Status:", result.originality_review.status)

print()

print(
    "Originality Score:",
    result.originality_review.originality_score,
)
print(
    "Human Value:",
    result.originality_review.human_value_score,
)

assert result.research is not None
assert result.script is not None
assert result.originality_review is not None
assert result.current_stage == WorkflowStage.QUALITY_CHECK

print()
print("Content Pipeline tests completed successfully.")