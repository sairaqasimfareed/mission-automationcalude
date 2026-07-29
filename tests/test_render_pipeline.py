from src.models.render_result import RenderStatus
from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)
from src.services.render_pipeline import RenderPipeline


script = Script(
    title="Hidden Underground Cities",
    content=(
        "Beneath ordinary streets, entire cities once existed. "
        "People lived underground for centuries. "
        "Some cities contained homes, tunnels and food storage."
    ),
    prompt_version="script_prompt_v1.0.0",
    word_count=22,
    estimated_duration_seconds=24,
    status=ScriptStatus.APPROVED,
    claude_review_status=ScriptReviewStatus.APPROVED,
)

pipeline = RenderPipeline()

result = pipeline.run(script)

print("Success:", result.success)
print("Status:", result.status)
print("Engine:", result.render_engine)
print("Duration:", result.duration_seconds)
print("Output:", result.output_file)

assert result.success is True
assert result.status == RenderStatus.COMPLETED
assert result.duration_seconds == 24

print("Render Pipeline tests completed successfully.")