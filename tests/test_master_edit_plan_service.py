from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.master_edit_plan import (
    MasterEditPlanStatus,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.master_edit_plan_service import (
    MasterEditPlanService,
)


def build_preset_reference(
    *,
    directive_path: str,
    requested_preset_id: str,
    resolved_preset_id: str | None = None,
) -> ResolvedPresetReference:
    """Build one exact-match resolved preset reference."""

    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=requested_preset_id,
        resolved_preset_id=(
            resolved_preset_id
            or requested_preset_id
        ),
        found_exact_match=True,
        used_fallback=False,
        implementation={},
        metadata={},
    )


def build_editing_blueprint(
    *,
    scene_number: int,
) -> ResolvedSceneEditingBlueprint:
    """Build one minimal resolved editing blueprint."""

    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=build_preset_reference(
            directive_path="genre_preset_id",
            requested_preset_id="genre.default",
        ),
        camera=ResolvedCameraInstruction(
            preset=build_preset_reference(
                directive_path="camera.preset_id",
                requested_preset_id="camera.none",
            ),
            intensity=DirectiveIntensity.MEDIUM,
            start_offset_seconds=0.0,
        ),
        transition_in=(
            ResolvedTransitionInstruction(
                preset=build_preset_reference(
                    directive_path=(
                        "transition_in.preset_id"
                    ),
                    requested_preset_id=(
                        "transition.cut"
                    ),
                ),
                duration_seconds=0.0,
                intensity=(
                    DirectiveIntensity.MEDIUM
                ),
            )
        ),
        transition_out=(
            ResolvedTransitionInstruction(
                preset=build_preset_reference(
                    directive_path=(
                        "transition_out.preset_id"
                    ),
                    requested_preset_id=(
                        "transition.cut"
                    ),
                ),
                duration_seconds=0.0,
                intensity=(
                    DirectiveIntensity.MEDIUM
                ),
            )
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=build_preset_reference(
                directive_path="music.preset_id",
                requested_preset_id="music.none",
            ),
            intensity=DirectiveIntensity.LOW,
            volume_percent=25.0,
            fade_in_seconds=0.0,
            fade_out_seconds=0.0,
            duck_under_voice=True,
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=build_preset_reference(
                directive_path=(
                    "subtitles.preset_id"
                ),
                requested_preset_id=(
                    "subtitle.none"
                ),
            ),
            animation_preset=None,
            enabled=False,
            burn_into_video=False,
            maximum_words_per_line=8,
        ),
        status=(
            BlueprintResolutionStatus.RESOLVED
        ),
        fallback_count=0,
        exact_match_count=6,
        warnings=[],
        metadata={},
    )


def build_video_clip(
    *,
    scene_number: int,
    duration_seconds: int,
    status: VideoClipStatus = (
        VideoClipStatus.READY
    ),
) -> VideoClip:
    """Build one video clip for master-plan tests."""

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
            f"scene_{scene_number:03}.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=status,
    )


def build_video_timeline(
    *,
    durations: list[int],
    include_blueprints: bool = True,
    clip_status: VideoClipStatus = (
        VideoClipStatus.READY
    ),
) -> VideoTimeline:
    """Build a sequential explicit video timeline."""

    clips: list[VideoClip] = []
    items: list[VideoTimelineItem] = []

    current_time = 0.0

    for index, duration_seconds in enumerate(
        durations,
        start=1,
    ):
        clip = build_video_clip(
            scene_number=index,
            duration_seconds=duration_seconds,
            status=clip_status,
        )

        clips.append(clip)

        end_time = (
            current_time
            + float(duration_seconds)
        )

        blueprint = (
            build_editing_blueprint(
                scene_number=index,
            )
            if include_blueprints
            else None
        )

        items.append(
            VideoTimelineItem(
                clip=clip,
                scene_number=index,
                start_time_seconds=(
                    current_time
                ),
                end_time_seconds=end_time,
                track_index=0,
                layer_index=0,
                enabled=True,
                editing_blueprint=blueprint,
            )
        )

        current_time = end_time

    return VideoTimeline(
        clips=clips,
        items=items,
        total_duration_seconds=current_time,
        output_resolution="1920x1080",
        frame_rate=30,
    )


def build_voice_track(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: float,
    status: AudioTrackStatus = (
        AudioTrackStatus.READY
    ),
) -> AudioTrack:
    """Build one scene-mapped voiceover track."""

    return AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=(
            "outputs/audio/"
            f"scene_{scene_number:03}.wav"
        ),
        start_time_seconds=(
            start_time_seconds
        ),
        duration_seconds=duration_seconds,
        volume=1.0,
        fade_in_seconds=0.0,
        fade_out_seconds=0.0,
        loop_enabled=False,
        duck_under_voice=False,
        provider="Dummy Voice",
        license_type="generated",
        status=status,
        metadata={
            "scene_number": scene_number,
            "primary_voice": True,
        },
    )


def build_ready_audio_timeline() -> AudioTimeline:
    """Build audio matching a 15-second video timeline."""

    return AudioTimeline(
        tracks=[
            build_voice_track(
                scene_number=1,
                start_time_seconds=0.0,
                duration_seconds=8.0,
            ),
            build_voice_track(
                scene_number=2,
                start_time_seconds=8.0,
                duration_seconds=7.0,
            ),
        ],
        sample_rate=48000,
        channels=2,
    )


service = MasterEditPlanService()


# --------------------------------------------------
# Fully ready master edit plan
# --------------------------------------------------

ready_video_timeline = build_video_timeline(
    durations=[
        8,
        7,
    ],
)

ready_audio_timeline = (
    build_ready_audio_timeline()
)

ready_plan = service.build(
    video_timeline=ready_video_timeline,
    audio_timeline=ready_audio_timeline,
    duration_tolerance_seconds=0.5,
    metadata={
        "project_name": (
            "Master Edit Plan Test"
        ),
    },
)

print(
    "Ready status:",
    ready_plan.status,
)

print(
    "Ready for render:",
    ready_plan.ready_for_render,
)

print(
    "Total duration:",
    ready_plan.total_duration_seconds,
)

assert (
    ready_plan.status
    == MasterEditPlanStatus.READY_FOR_RENDER
)

assert ready_plan.ready_for_render is True
assert ready_plan.video_ready is True
assert ready_plan.editing_ready is True
assert ready_plan.voice_ready is True
assert ready_plan.audio_ready is True
assert ready_plan.duration_compatible is True

assert ready_plan.scene_count == 2
assert ready_plan.video_item_count == 2
assert ready_plan.enabled_video_item_count == 2
assert ready_plan.audio_track_count == 2
assert ready_plan.voice_track_count == 2
assert ready_plan.music_track_count == 0
assert ready_plan.sound_effect_track_count == 0
assert ready_plan.total_track_count == 4

assert (
    ready_plan.video_duration_seconds
    == 15.0
)

assert (
    ready_plan.audio_duration_seconds
    == 15.0
)

assert (
    ready_plan.total_duration_seconds
    == 15.0
)

assert (
    ready_plan.duration_difference_seconds
    == 0.0
)

assert ready_plan.has_video is True
assert ready_plan.has_audio is True
assert ready_plan.is_empty is False

assert (
    ready_plan.metadata["project_name"]
    == "Master Edit Plan Test"
)

assert (
    ready_plan.metadata[
        "ready_for_render"
    ]
    is True
)

assert service.can_render(
    ready_plan
) is True


# --------------------------------------------------
# Summary
# --------------------------------------------------

ready_summary = service.summary(
    ready_plan
)

assert (
    ready_summary["status"]
    == "ready_for_render"
)

assert ready_summary["scene_count"] == 2

assert (
    ready_summary["voice_track_count"]
    == 2
)

assert (
    ready_summary[
        "total_duration_seconds"
    ]
    == 15.0
)

assert (
    ready_summary["ready_for_render"]
    is True
)

assert (
    ready_summary["output_file"]
    is None
)


# --------------------------------------------------
# Rendering lifecycle
# --------------------------------------------------

rendering_plan = service.mark_rendering(
    ready_plan
)

assert (
    rendering_plan.status
    == MasterEditPlanStatus.RENDERING
)

assert (
    rendering_plan.metadata[
        "render_started"
    ]
    is True
)

assert (
    rendering_plan.metadata[
        "render_completed"
    ]
    is False
)


try:
    service.refresh(
        rendering_plan
    )
except ValueError:
    print(
        "Rendering plan refresh "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Rendering plans should not refresh."
    )


completed_plan = service.mark_completed(
    rendering_plan,
    output_file=(
        "outputs/video/final_master.mp4"
    ),
)

assert (
    completed_plan.status
    == MasterEditPlanStatus.COMPLETED
)

assert (
    completed_plan
    .video_timeline
    .output_file
    == "outputs/video/final_master.mp4"
)

assert (
    completed_plan.metadata[
        "render_completed"
    ]
    is True
)

assert (
    completed_plan.metadata[
        "final_output_file"
    ]
    == "outputs/video/final_master.mp4"
)


completed_summary = service.summary(
    completed_plan
)

assert (
    completed_summary["output_file"]
    == "outputs/video/final_master.mp4"
)


try:
    service.refresh(
        completed_plan
    )
except ValueError:
    print(
        "Completed plan refresh "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Completed plans should not refresh."
    )


try:
    service.mark_failed(
        completed_plan,
        error_message=(
            "Completed plan should not fail."
        ),
    )
except ValueError:
    print(
        "Completed plan failure transition "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Completed plans cannot become failed."
    )


# --------------------------------------------------
# Empty plan
# --------------------------------------------------

empty_plan = service.build(
    video_timeline=VideoTimeline(),
    audio_timeline=AudioTimeline(),
)

assert (
    empty_plan.status
    == MasterEditPlanStatus.DRAFT
)

assert empty_plan.ready_for_render is False
assert empty_plan.scene_count == 0
assert empty_plan.video_item_count == 0
assert empty_plan.audio_track_count == 0
assert empty_plan.is_empty is True
assert empty_plan.has_video is False
assert empty_plan.has_audio is False
assert empty_plan.warnings


try:
    service.validate_render_ready(
        empty_plan
    )
except ValueError as exc:
    assert "not ready" in str(exc).lower()

    print(
        "Empty master edit plan "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Empty plan should not be render-ready."
    )


# --------------------------------------------------
# Video exists but editing blueprints are missing
# --------------------------------------------------

missing_editing_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
        include_blueprints=False,
    ),
    audio_timeline=(
        build_ready_audio_timeline()
    ),
)

assert missing_editing_plan.video_ready is True

assert (
    missing_editing_plan.editing_ready
    is False
)

assert (
    missing_editing_plan.ready_for_render
    is False
)

assert any(
    "editing" in warning.lower()
    for warning in (
        missing_editing_plan.warnings
    )
)


try:
    service.mark_rendering(
        missing_editing_plan
    )
except ValueError:
    print(
        "Missing editing blueprint plan "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Plan without editing blueprints "
        "should not render."
    )


# --------------------------------------------------
# Audio missing
# --------------------------------------------------

video_only_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=AudioTimeline(),
)

assert video_only_plan.video_ready is True
assert video_only_plan.editing_ready is True
assert video_only_plan.voice_ready is False
assert video_only_plan.audio_ready is False
assert video_only_plan.duration_compatible is False
assert video_only_plan.ready_for_render is False

assert any(
    "audio" in warning.lower()
    for warning in video_only_plan.warnings
)


# --------------------------------------------------
# Audio exists without video
# --------------------------------------------------

audio_only_plan = service.build(
    video_timeline=VideoTimeline(),
    audio_timeline=(
        build_ready_audio_timeline()
    ),
)

assert audio_only_plan.video_ready is False
assert audio_only_plan.editing_ready is False
assert audio_only_plan.voice_ready is True
assert audio_only_plan.audio_ready is True
assert audio_only_plan.duration_compatible is False
assert audio_only_plan.ready_for_render is False


# --------------------------------------------------
# Audio duration exceeds video duration
# --------------------------------------------------

long_audio_timeline = AudioTimeline(
    tracks=[
        build_voice_track(
            scene_number=1,
            start_time_seconds=0.0,
            duration_seconds=20.0,
        )
    ]
)

duration_mismatch_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=long_audio_timeline,
    duration_tolerance_seconds=0.5,
)

assert (
    duration_mismatch_plan
    .video_duration_seconds
    == 15.0
)

assert (
    duration_mismatch_plan
    .audio_duration_seconds
    == 20.0
)

assert (
    duration_mismatch_plan
    .duration_difference_seconds
    == 5.0
)

assert (
    duration_mismatch_plan
    .duration_compatible
    is False
)

assert (
    duration_mismatch_plan
    .ready_for_render
    is False
)

assert any(
    "exceeds video duration"
    in warning.lower()
    for warning in (
        duration_mismatch_plan.warnings
    )
)


# --------------------------------------------------
# Tolerance permits a small audio overrun
# --------------------------------------------------

small_overrun_audio = AudioTimeline(
    tracks=[
        build_voice_track(
            scene_number=1,
            start_time_seconds=0.0,
            duration_seconds=15.4,
        )
    ]
)

tolerated_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=small_overrun_audio,
    duration_tolerance_seconds=0.5,
)

assert (
    tolerated_plan.duration_compatible
    is True
)

assert tolerated_plan.ready_for_render is True


# --------------------------------------------------
# Audio ends before video
# --------------------------------------------------

short_audio_timeline = AudioTimeline(
    tracks=[
        build_voice_track(
            scene_number=1,
            start_time_seconds=0.0,
            duration_seconds=10.0,
        )
    ]
)

short_audio_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=short_audio_timeline,
    duration_tolerance_seconds=0.5,
)

assert short_audio_plan.duration_compatible is True
assert short_audio_plan.ready_for_render is True

assert any(
    "audio ends before"
    in warning.lower()
    for warning in (
        short_audio_plan.warnings
    )
)


# --------------------------------------------------
# Non-ready audio track
# --------------------------------------------------

pending_audio_timeline = AudioTimeline(
    tracks=[
        build_voice_track(
            scene_number=1,
            start_time_seconds=0.0,
            duration_seconds=15.0,
            status=AudioTrackStatus.PENDING,
        )
    ]
)

pending_audio_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=pending_audio_timeline,
)

assert pending_audio_plan.voice_ready is False
assert pending_audio_plan.audio_ready is False
assert pending_audio_plan.ready_for_render is False


# --------------------------------------------------
# Refresh after timeline mutation
# --------------------------------------------------

refresh_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=(
        build_ready_audio_timeline()
    ),
)

assert refresh_plan.ready_for_render is True

refresh_plan.audio_timeline.tracks[
    1
].duration_seconds = 12.0

service.refresh(
    refresh_plan
)

assert (
    refresh_plan.audio_duration_seconds
    == 20.0
)

assert refresh_plan.duration_compatible is False
assert refresh_plan.ready_for_render is False

refresh_plan.audio_timeline.tracks[
    1
].duration_seconds = 7.0

service.refresh(
    refresh_plan
)

assert (
    refresh_plan.audio_duration_seconds
    == 15.0
)

assert refresh_plan.duration_compatible is True
assert refresh_plan.ready_for_render is True


# --------------------------------------------------
# Failed lifecycle
# --------------------------------------------------

failure_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=(
        build_ready_audio_timeline()
    ),
)

service.mark_failed(
    failure_plan,
    error_message=(
        "Simulated composition failure."
    ),
    failure_metadata={
        "engine": "dry-run",
        "stage": "composition",
    },
)

assert (
    failure_plan.status
    == MasterEditPlanStatus.FAILED
)

assert (
    failure_plan.metadata[
        "failure_message"
    ]
    == "Simulated composition failure."
)

assert (
    failure_plan.metadata[
        "failure_details"
    ]["stage"]
    == "composition"
)

assert any(
    "simulated composition failure"
    in warning.lower()
    for warning in failure_plan.warnings
)


try:
    service.mark_failed(
        failure_plan,
        error_message="   ",
    )
except ValueError:
    print(
        "Empty failure message "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Empty failure message should fail."
    )


# --------------------------------------------------
# Invalid duration tolerance
# --------------------------------------------------

try:
    service.build(
        video_timeline=VideoTimeline(),
        audio_timeline=AudioTimeline(),
        duration_tolerance_seconds=-1.0,
    )
except ValueError:
    print(
        "Negative duration tolerance "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Negative duration tolerance "
        "should fail."
    )


# --------------------------------------------------
# Serialization
# --------------------------------------------------

serialization_plan = service.build(
    video_timeline=build_video_timeline(
        durations=[
            8,
            7,
        ],
    ),
    audio_timeline=(
        build_ready_audio_timeline()
    ),
)

serialized = (
    serialization_plan.model_dump_json()
)

restored = (
    serialization_plan.__class__
    .model_validate_json(
        serialized
    )
)

assert restored == serialization_plan


print(
    "Master Edit Plan Service tests "
    "completed successfully."
)