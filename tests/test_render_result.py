from src.models.render_result import (
    RenderResult,
    RenderStatus,
)


result = RenderResult(
    success=True,
    output_file="outputs/final_video.mp4",
    render_engine="ffmpeg",
    render_time_seconds=42.5,
    duration_seconds=180,
    status=RenderStatus.COMPLETED,
)

print("Success:", result.success)
print("Output:", result.output_file)
print("Engine:", result.render_engine)
print("Status:", result.status)
print("Duration:", result.duration_seconds)

assert result.success is True
assert result.status == RenderStatus.COMPLETED
assert result.render_engine == "ffmpeg"

print("Render Result tests completed successfully.")