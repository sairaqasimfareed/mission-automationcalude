from src.models.video_job import VideoJob
from src.pipeline.pipeline_stage import PipelineStageName
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext


class DummyService:
    def run(self) -> str:
        return "service-ready"


job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery",
    topic="Hidden Underground Cities",
)

pipeline_state = PipelineState(
    current_stage=PipelineStageName.RESEARCH,
)

context = StageContext(
    job=job,
    pipeline_state=pipeline_state,
    dry_run=True,
)

context.add_service(
    "dummy",
    DummyService(),
)

service = context.get_service("dummy")

context.temporary_data["research_prompt"] = (
    "Research hidden underground cities."
)

context.user_input["approved"] = True

print("Job topic:", context.job.topic)
print("Current stage:", context.pipeline_state.current_stage)
print("Dry run:", context.dry_run)
print("Service result:", service.run())
print(
    "Temporary prompt:",
    context.temporary_data["research_prompt"],
)
print(
    "User approved:",
    context.user_input["approved"],
)

assert context.job.topic == "Hidden Underground Cities"
assert context.dry_run is True
assert service.run() == "service-ready"
assert context.user_input["approved"] is True

try:
    context.get_service("missing")
except KeyError:
    print("Missing service successfully blocked.")
else:
    raise AssertionError(
        "Missing service should raise KeyError."
    )

print("Stage Context tests completed successfully.")