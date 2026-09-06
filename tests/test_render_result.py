from src.models.render_failure_diagnosis import RenderFailureCategory
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

# Post-Script-Approval Production Plan, Phase 14: new fields default
# to unset so an old RenderResult (or one built by a caller that
# never sets them) is unaffected.
assert result.ffmpeg_command == []
assert result.exit_code is None
assert result.ffmpeg_version is None
assert result.selected_video_codec is None
assert result.selected_audio_codec is None
assert result.selected_hardware_acceleration is None
assert result.failure_category is None

print("Default Phase 14 provenance fields " "successfully left unset.")

diagnosed_failure = RenderResult(
    success=False,
    output_file=None,
    render_engine="ffmpeg",
    render_time_seconds=3.0,
    duration_seconds=0,
    status=RenderStatus.FAILED,
    error_message="FFmpeg exited with an error.",
    ffmpeg_command=["ffmpeg", "-y", "-i", "input.mp4", "output.mp4.part"],
    exit_code=1,
    ffmpeg_version="6.0",
    selected_video_codec="libx264",
    selected_audio_codec="aac",
    selected_hardware_acceleration="nvenc",
    failure_category=RenderFailureCategory.COMMAND_OR_MEDIA,
)

assert diagnosed_failure.ffmpeg_command == [
    "ffmpeg",
    "-y",
    "-i",
    "input.mp4",
    "output.mp4.part",
]
assert diagnosed_failure.exit_code == 1
assert diagnosed_failure.ffmpeg_version == "6.0"
assert diagnosed_failure.selected_video_codec == "libx264"
assert diagnosed_failure.selected_audio_codec == "aac"
assert diagnosed_failure.selected_hardware_acceleration == "nvenc"
assert diagnosed_failure.failure_category == RenderFailureCategory.COMMAND_OR_MEDIA

print("Explicit Phase 14 provenance fields " "stored correctly.")

restored_failure = diagnosed_failure.__class__.model_validate_json(
    diagnosed_failure.model_dump_json()
)

assert restored_failure.failure_category == RenderFailureCategory.COMMAND_OR_MEDIA
assert restored_failure.ffmpeg_command == diagnosed_failure.ffmpeg_command

print("Phase 14 provenance fields round-trip " "through serialization.")

print("Render Result tests completed successfully.")
