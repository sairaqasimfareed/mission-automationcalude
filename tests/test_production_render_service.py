from __future__ import annotations

from unittest.mock import MagicMock

from src.models.ffmpeg_execution_result import (
    FFmpegExecutionStatus,
)
from src.models.render_result import RenderStatus
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.services.production_render_service import (
    ProductionRenderService,
)


def _service_dependencies() -> dict[
    str,
    MagicMock,
]:
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


def test_render_executes_real_render_chain() -> None:
    dependencies = _service_dependencies()

    video_timeline = MagicMock()
    video_timeline.calculate_duration.return_value = 12.5

    audio_timeline = MagicMock()

    voice_blueprints: list[ResolvedVoiceBlueprint] = [
        MagicMock(
            spec=ResolvedVoiceBlueprint,
        ),
    ]

    master_plan = MagicMock()
    master_plan.warnings = [
        "master warning",
    ]

    transition_plan = MagicMock()
    effect_plan = MagicMock()
    subtitle_plan = MagicMock()
    camera_plan = MagicMock()
    animation_plan = MagicMock()

    render_graph = MagicMock()
    render_graph.warnings = [
        "graph warning",
    ]

    resolved_config = MagicMock()
    resolved_config.warnings = [
        "codec warning",
    ]
    resolved_config.config.timeout_seconds = 3600.0

    filter_graph = MagicMock()
    command_plan = MagicMock()

    execution_result = MagicMock()
    execution_result.success = True
    execution_result.output_file = "outputs/test.mp4"
    execution_result.elapsed_seconds = 2.25
    execution_result.error_message = None
    execution_result.exit_code = 0
    execution_result.status = FFmpegExecutionStatus.SUCCEEDED

    dependencies["master_edit_plan_service"].build.return_value = master_plan

    dependencies["transition_execution_service"].build_plan.return_value = (
        transition_plan
    )

    dependencies["effect_execution_service"].build_plan.return_value = effect_plan

    dependencies["subtitle_execution_service"].build_plan.return_value = subtitle_plan

    dependencies["camera_execution_service"].build_plan.return_value = camera_plan

    dependencies["animation_execution_service"].build_plan.return_value = animation_plan

    dependencies["render_graph_builder_service"].build.return_value = render_graph

    dependencies["ffmpeg_capability_service"].resolve.return_value = resolved_config

    dependencies["filter_graph_builder_service"].build.return_value = filter_graph

    dependencies["ffmpeg_command_builder_service"].build.return_value = command_plan

    dependencies["ffmpeg_execution_service"].execute.return_value = execution_result

    service = ProductionRenderService(
        master_edit_plan_service=(dependencies["master_edit_plan_service"]),
        transition_execution_service=(dependencies["transition_execution_service"]),
        effect_execution_service=(dependencies["effect_execution_service"]),
        subtitle_execution_service=(dependencies["subtitle_execution_service"]),
        camera_execution_service=(dependencies["camera_execution_service"]),
        animation_execution_service=(dependencies["animation_execution_service"]),
        render_graph_builder_service=(dependencies["render_graph_builder_service"]),
        ffmpeg_capability_service=(dependencies["ffmpeg_capability_service"]),
        filter_graph_builder_service=(dependencies["filter_graph_builder_service"]),
        ffmpeg_command_builder_service=(dependencies["ffmpeg_command_builder_service"]),
        ffmpeg_execution_service=(dependencies["ffmpeg_execution_service"]),
    )

    result = service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=voice_blueprints,
        output_file="outputs/test.mp4",
    )

    assert result.success is True
    assert result.status == RenderStatus.COMPLETED
    assert result.render_engine == "ffmpeg"
    assert result.output_file == "outputs/test.mp4"
    assert result.render_time_seconds == 2.25
    assert result.duration_seconds == 12

    assert result.warnings == [
        "master warning",
        "graph warning",
        "codec warning",
    ]

    dependencies["master_edit_plan_service"].build.assert_called_once_with(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
    )

    dependencies["subtitle_execution_service"].build_plan.assert_called_once_with(
        video_timeline,
        voice_blueprints=voice_blueprints,
        mark_ready=True,
    )

    dependencies["ffmpeg_execution_service"].execute.assert_called_once_with(
        command_plan,
        total_duration_seconds=12.5,
        timeout_seconds=3600.0,
        progress_callback=None,
    )

    dependencies["master_edit_plan_service"].mark_completed.assert_called_once_with(
        master_plan,
        output_file="outputs/test.mp4",
    )


def test_render_maps_ffmpeg_failure() -> None:
    dependencies = _service_dependencies()

    video_timeline = MagicMock()
    video_timeline.calculate_duration.return_value = 8.0

    audio_timeline = MagicMock()

    voice_blueprints: list[ResolvedVoiceBlueprint] = [
        MagicMock(
            spec=ResolvedVoiceBlueprint,
        ),
    ]

    master_plan = MagicMock()
    master_plan.warnings = []

    render_graph = MagicMock()
    render_graph.warnings = []

    resolved_config = MagicMock()
    resolved_config.warnings = []
    resolved_config.config.timeout_seconds = 300.0

    execution_result = MagicMock()
    execution_result.success = False
    execution_result.output_file = None
    execution_result.elapsed_seconds = 1.5
    execution_result.error_message = "FFmpeg render failed."
    execution_result.exit_code = 1
    execution_result.status = FFmpegExecutionStatus.FAILED

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

    service = ProductionRenderService(
        master_edit_plan_service=(dependencies["master_edit_plan_service"]),
        transition_execution_service=(dependencies["transition_execution_service"]),
        effect_execution_service=(dependencies["effect_execution_service"]),
        subtitle_execution_service=(dependencies["subtitle_execution_service"]),
        camera_execution_service=(dependencies["camera_execution_service"]),
        animation_execution_service=(dependencies["animation_execution_service"]),
        render_graph_builder_service=(dependencies["render_graph_builder_service"]),
        ffmpeg_capability_service=(dependencies["ffmpeg_capability_service"]),
        filter_graph_builder_service=(dependencies["filter_graph_builder_service"]),
        ffmpeg_command_builder_service=(dependencies["ffmpeg_command_builder_service"]),
        ffmpeg_execution_service=(dependencies["ffmpeg_execution_service"]),
    )

    result = service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=voice_blueprints,
    )

    assert result.success is False
    assert result.status == RenderStatus.FAILED
    assert result.render_engine == "ffmpeg"
    assert result.output_file is None
    assert result.error_message == "FFmpeg render failed."

    dependencies["master_edit_plan_service"].mark_failed.assert_called_once()

    dependencies["master_edit_plan_service"].mark_completed.assert_not_called()


def test_constructor_rejects_empty_output_file() -> None:
    try:
        ProductionRenderService(
            output_file="   ",
        )
    except ValueError as error:
        assert str(error) == ("Production render output file " "cannot be empty.")
    else:
        raise AssertionError("Expected ValueError.")


def test_render_rejects_missing_voice_blueprints() -> None:
    service = ProductionRenderService()

    video_timeline = MagicMock()
    video_timeline.calculate_duration.return_value = 5.0

    try:
        service.render(
            video_timeline=video_timeline,
            audio_timeline=MagicMock(),
            voice_blueprints=[],
        )
    except ValueError as error:
        assert str(error) == (
            "Production rendering requires " "resolved voice blueprints."
        )
    else:
        raise AssertionError("Expected ValueError.")


def test_render_forwards_progress_callback_to_ffmpeg_execution() -> None:
    dependencies = _service_dependencies()

    video_timeline = MagicMock()
    video_timeline.calculate_duration.return_value = 5.0

    audio_timeline = MagicMock()

    voice_blueprints: list[ResolvedVoiceBlueprint] = [
        MagicMock(spec=ResolvedVoiceBlueprint),
    ]

    dependencies["master_edit_plan_service"].build.return_value = MagicMock(
        warnings=[],
    )
    dependencies["render_graph_builder_service"].build.return_value = MagicMock(
        warnings=[],
    )
    dependencies["ffmpeg_capability_service"].resolve.return_value = MagicMock(
        warnings=[],
    )

    execution_result = MagicMock()
    execution_result.success = True
    execution_result.status = FFmpegExecutionStatus.SUCCEEDED
    execution_result.error_message = None
    execution_result.output_file = "outputs/test.mp4"
    execution_result.elapsed_seconds = 2.25
    dependencies["ffmpeg_execution_service"].execute.return_value = execution_result

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

    def fake_progress_callback(progress: object) -> None:
        return None

    service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=voice_blueprints,
        progress_callback=fake_progress_callback,
    )

    dependencies["ffmpeg_execution_service"].execute.assert_called_once()
    call_kwargs = dependencies["ffmpeg_execution_service"].execute.call_args.kwargs
    assert call_kwargs["progress_callback"] is fake_progress_callback
