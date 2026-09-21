from __future__ import annotations

from unittest.mock import MagicMock

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.ffmpeg_execution_result import FFmpegExecutionStatus
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.video_clip import VideoClip
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.production_render_service import ProductionRenderService

_TRANSITION_DURATION_SECONDS = 1.0
_SCENE_DURATION_SECONDS = 4


def _service_dependencies() -> dict[str, MagicMock]:
    return {
        "master_edit_plan_service": MagicMock(),
        "transition_execution_service": MagicMock(),
        "effect_execution_service": MagicMock(),
        "subtitle_execution_service": MagicMock(),
        "camera_execution_service": MagicMock(),
        "animation_execution_service": MagicMock(),
        "render_graph_builder_service": MagicMock(),
        "ffmpeg_capability_service": MagicMock(),
        "filter_graph_builder_service": MagicMock(),
        "ffmpeg_command_builder_service": MagicMock(),
        "ffmpeg_execution_service": MagicMock(),
    }


def _video_item(scene_number: int) -> VideoTimelineItem:
    start = (scene_number - 1) * _SCENE_DURATION_SECONDS

    clip = VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        duration_seconds=_SCENE_DURATION_SECONDS,
        local_file=f"scene_{scene_number}.mp4",
        source_status=SceneSourceStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=float(start),
        end_time_seconds=float(start + _SCENE_DURATION_SECONDS),
    )


def _two_scene_video_timeline() -> VideoTimeline:
    return VideoTimeline(items=[_video_item(1), _video_item(2)])


def _wire_successful_render(dependencies: dict[str, MagicMock]) -> None:
    master_plan = MagicMock()
    master_plan.warnings = []

    resolved_config = MagicMock()
    resolved_config.warnings = []
    resolved_config.config.timeout_seconds = 3600.0
    resolved_config.capabilities.ffmpeg_version = "6.0"
    resolved_config.selected_video_codec = "libx264"
    resolved_config.selected_audio_codec = "aac"
    resolved_config.selected_hardware_acceleration = None

    render_graph = MagicMock()
    render_graph.warnings = []

    execution_result = MagicMock()
    execution_result.success = True
    execution_result.output_file = "outputs/test.mp4"
    execution_result.elapsed_seconds = 1.0
    execution_result.error_message = None
    execution_result.exit_code = 0
    execution_result.status = FFmpegExecutionStatus.SUCCEEDED
    execution_result.ffmpeg_command = ["ffmpeg", "-y", "outputs/test.mp4"]
    execution_result.metadata = {}

    dependencies["master_edit_plan_service"].build.return_value = master_plan
    dependencies["transition_execution_service"].build_plan.return_value = MagicMock()
    dependencies["effect_execution_service"].build_plan.return_value = MagicMock()
    dependencies["subtitle_execution_service"].build_plan.return_value = MagicMock()
    dependencies["camera_execution_service"].build_plan.return_value = MagicMock()
    dependencies["animation_execution_service"].build_plan.return_value = MagicMock()
    dependencies["render_graph_builder_service"].build.return_value = render_graph
    dependencies["ffmpeg_capability_service"].resolve.return_value = resolved_config
    dependencies["filter_graph_builder_service"].build.return_value = MagicMock()
    dependencies["ffmpeg_command_builder_service"].build.return_value = MagicMock()
    dependencies["ffmpeg_execution_service"].execute.return_value = execution_result


def test_single_chunk_render_clips_audio_to_the_real_video_length() -> None:
    """
    Real-world finding, 2026-09-18: a single-chunk render (short
    enough to never hit the chunked path at all) never applied the
    real-boundary audio correction _slice_for_scenes already gives
    the chunked path - confirmed on a real render, whose video stream
    measured 1.66s shorter than its audio stream because a trailing
    music/SFX track ran to the *nominal* video length instead of the
    real, crossfade-shortened one. render() must now route a
    single-chunk render through the same correction before building
    its command, so a background-music track positioned to the
    nominal end of a two-scene, one-crossfade timeline (nominal 8.0s)
    gets clipped to the real end (8.0 - 1.0 transition = 7.0s).
    """

    dependencies = _service_dependencies()

    _wire_successful_render(dependencies)

    video_timeline = _two_scene_video_timeline()

    music_track = AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="music.mp3",
        start_time_seconds=0.0,
        duration_seconds=8.0,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )

    audio_timeline = AudioTimeline(tracks=[music_track])

    voice_blueprints: list[ResolvedVoiceBlueprint] = [
        MagicMock(spec=ResolvedVoiceBlueprint, scene_number=1),
        MagicMock(spec=ResolvedVoiceBlueprint, scene_number=2),
    ]

    service = ProductionRenderService(
        master_edit_plan_service=dependencies["master_edit_plan_service"],
        transition_execution_service=dependencies["transition_execution_service"],
        effect_execution_service=dependencies["effect_execution_service"],
        subtitle_execution_service=dependencies["subtitle_execution_service"],
        camera_execution_service=dependencies["camera_execution_service"],
        animation_execution_service=dependencies["animation_execution_service"],
        render_graph_builder_service=dependencies["render_graph_builder_service"],
        ffmpeg_capability_service=dependencies["ffmpeg_capability_service"],
        filter_graph_builder_service=dependencies["filter_graph_builder_service"],
        ffmpeg_command_builder_service=dependencies["ffmpeg_command_builder_service"],
        ffmpeg_execution_service=dependencies["ffmpeg_execution_service"],
    )

    result = service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=voice_blueprints,
        output_file="outputs/test.mp4",
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
    )

    assert result.success is True

    final_call = dependencies["master_edit_plan_service"].build.call_args_list[-1]

    corrected_audio_timeline = final_call.kwargs["audio_timeline"]

    assert len(corrected_audio_timeline.tracks) == 1

    corrected_track = corrected_audio_timeline.tracks[0]

    assert corrected_track.start_time_seconds == 0.0

    assert corrected_track.duration_seconds == 7.0

    corrected_video_timeline = final_call.kwargs["video_timeline"]

    assert corrected_video_timeline.calculate_duration() == 8.0


def test_single_chunk_render_with_no_transition_duration_is_unchanged() -> None:
    """
    transition_duration_seconds defaults to 0.0 (no genre profile
    resolved, or a render that never needs chunking regardless) -
    the correction must not run at all, leaving the original,
    uncorrected audio_timeline exactly as given, matching this
    method's behavior before this fix.
    """

    dependencies = _service_dependencies()

    _wire_successful_render(dependencies)

    video_timeline = _two_scene_video_timeline()

    music_track = AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="music.mp3",
        start_time_seconds=0.0,
        duration_seconds=8.0,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )

    audio_timeline = AudioTimeline(tracks=[music_track])

    voice_blueprints: list[ResolvedVoiceBlueprint] = [
        MagicMock(spec=ResolvedVoiceBlueprint, scene_number=1),
        MagicMock(spec=ResolvedVoiceBlueprint, scene_number=2),
    ]

    service = ProductionRenderService(
        master_edit_plan_service=dependencies["master_edit_plan_service"],
        transition_execution_service=dependencies["transition_execution_service"],
        effect_execution_service=dependencies["effect_execution_service"],
        subtitle_execution_service=dependencies["subtitle_execution_service"],
        camera_execution_service=dependencies["camera_execution_service"],
        animation_execution_service=dependencies["animation_execution_service"],
        render_graph_builder_service=dependencies["render_graph_builder_service"],
        ffmpeg_capability_service=dependencies["ffmpeg_capability_service"],
        filter_graph_builder_service=dependencies["filter_graph_builder_service"],
        ffmpeg_command_builder_service=dependencies["ffmpeg_command_builder_service"],
        ffmpeg_execution_service=dependencies["ffmpeg_execution_service"],
    )

    result = service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=voice_blueprints,
        output_file="outputs/test.mp4",
    )

    assert result.success is True

    dependencies["master_edit_plan_service"].build.assert_called_once_with(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
    )
