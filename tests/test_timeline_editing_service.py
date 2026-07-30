from __future__ import annotations

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.services.timeline_builder_service import (
    TimelineBuilderService,
)
from src.services.timeline_editing_service import (
    TimelineEditingService,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


def build_clip(
    *,
    scene_number: int,
    duration_seconds: int,
    file_name: str,
) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            f"{file_name}"
        ),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


clips = [
    build_clip(
        scene_number=1,
        duration_seconds=8,
        file_name="scene_001.mp4",
    ),
    build_clip(
        scene_number=2,
        duration_seconds=8,
        file_name="scene_002.mp4",
    ),
    build_clip(
        scene_number=3,
        duration_seconds=10,
        file_name="scene_003.mp4",
    ),
]

builder = TimelineBuilderService()
editor = TimelineEditingService()
validator = TimelineValidationService()

timeline = builder.build(clips)

assert timeline.calculate_duration() == 26.0


disabled_item = editor.disable_scene(
    timeline,
    scene_number=2,
)

assert disabled_item.enabled is False
assert timeline.calculate_duration() == 26.0

enabled_item = editor.enable_scene(
    timeline,
    scene_number=2,
)

assert enabled_item.enabled is True


moved_item = editor.move_scene(
    timeline,
    scene_number=2,
    new_start_time_seconds=12.0,
)

assert moved_item.start_time_seconds == 12.0
assert moved_item.end_time_seconds == 20.0

gap_result = validator.validate(timeline)

assert gap_result.is_valid is False
assert gap_result.gap_duration_seconds > 0


compacted_count = editor.compact_primary_track(
    timeline
)

assert compacted_count == 3
assert timeline.items[0].start_time_seconds == 0.0
assert timeline.items[1].start_time_seconds == 8.0
assert timeline.items[2].start_time_seconds == 16.0

compacted_result = validator.validate(
    timeline
)

assert compacted_result.is_valid is True


replacement_clip = build_clip(
    scene_number=2,
    duration_seconds=12,
    file_name="scene_002_replacement.mp4",
)

replaced_item = editor.replace_scene_clip(
    timeline,
    scene_number=2,
    replacement_clip=replacement_clip,
)

assert (
    replaced_item.clip.local_file
    == (
        "assets/videos/manual/"
        "scene_002_replacement.mp4"
    )
)

assert replaced_item.duration_seconds == 12.0

assert any(
    clip.local_file
    == (
        "assets/videos/manual/"
        "scene_002_replacement.mp4"
    )
    for clip in timeline.clips
)

# Replacement changed duration, so compact again.
editor.compact_primary_track(timeline)

assert timeline.calculate_duration() == 30.0

valid_after_replacement = validator.validate(
    timeline
)

assert valid_after_replacement.is_valid is True


removed_item = editor.remove_scene(
    timeline,
    scene_number=2,
)

assert removed_item.scene_number == 2
assert len(timeline.items) == 2
assert len(timeline.clips) == 2

# Removing scene 2 leaves a gap until compacted.
removed_result = validator.validate(
    timeline
)

assert removed_result.is_valid is False

editor.compact_primary_track(timeline)

final_result = validator.validate(
    timeline
)

assert final_result.is_valid is True
assert timeline.calculate_duration() == 18.0


try:
    editor.move_scene(
        timeline,
        scene_number=99,
        new_start_time_seconds=5.0,
    )
except KeyError:
    print(
        "Missing timeline scene successfully blocked."
    )
else:
    raise AssertionError(
        "Missing timeline scene should fail."
    )


try:
    editor.move_scene(
        timeline,
        scene_number=1,
        new_start_time_seconds=-1.0,
    )
except ValueError:
    print(
        "Negative timeline position successfully blocked."
    )
else:
    raise AssertionError(
        "Negative timeline position should fail."
    )


print(
    "Timeline Editing Service tests "
    "completed successfully."
)