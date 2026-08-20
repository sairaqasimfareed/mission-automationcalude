from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.render_result import (
    RenderResult,
    RenderStatus,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline


def build_job(
    *,
    status: JobStatus,
    stage: WorkflowStage,
) -> VideoJob:
    """Build the minimum valid orchestration test job."""

    return VideoJob(
        project_name="Mission Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Render orchestration",
        status=status,
        current_stage=stage,
    )


def test_failed_result() -> None:
    job = build_job(
        status=JobStatus.FAILED,
        stage=WorkflowStage.RENDER,
    )

    result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.RENDER,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
            WorkflowStage.EDITING,
        ],
        elapsed_seconds=2.5,
        error_message="Synthetic render failure.",
    )

    assert result.success is False
    assert result.is_failed is True
    assert result.is_terminal is True
    assert result.has_errors is True

    assert result.failed_stage == WorkflowStage.RENDER

    assert result.completed_stage_count == 3

    assert "Synthetic render failure." in result.diagnostic_summary


def test_cancelled_result() -> None:
    job = build_job(
        status=JobStatus.CANCELLED,
        stage=WorkflowStage.ASSET_GENERATION,
    )

    result = RenderOrchestrationResult.cancelled(
        job=job,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
        ],
        elapsed_seconds=1.0,
    )

    assert result.success is False
    assert result.is_cancelled is True
    assert result.is_terminal is True
    assert result.failed_stage is None

    assert "cancelled" in result.diagnostic_summary.lower()


def test_success_result() -> None:
    job = build_job(
        status=JobStatus.COMPLETED,
        stage=WorkflowStage.READY_FOR_UPLOAD,
    )

    research = ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )

    script = Script(
        title="Synthetic orchestration script",
        content="Synthetic narration for orchestration testing.",
        prompt_version="test-1.0",
        word_count=5,
        estimated_duration_seconds=30,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title="Synthetic Scene",
        narration=("Synthetic narration for orchestration testing."),
        visual_prompt="Synthetic visual prompt.",
        estimated_duration_seconds=30,
        manual_file_path=("assets/videos/manual/test_scene.mp4"),
        source_status=SceneSourceStatus.READY,
        status=SceneStatus.READY,
    )

    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=30,
        prompt="Synthetic orchestration test scene.",
        provider="Manual Upload",
        local_file="assets/videos/manual/test_scene.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    job.research = research
    job.script = script

    job.scenes = [
        scene,
    ]

    job.voice_file = "assets/audio/test_voice.wav"

    job.video_clips = [
        clip,
    ]

    job.video_timeline = VideoTimeline(
        clips=[
            clip,
        ],
    )

    job.video_timeline.calculate_duration()

    job.audio_timeline = AudioTimeline()

    render_result = RenderResult(
        success=True,
        output_file="outputs/final_video.mp4",
        render_engine="ffmpeg",
        render_time_seconds=2.0,
        duration_seconds=30,
        status=RenderStatus.COMPLETED,
    )

    job.render_result = render_result

    result = RenderOrchestrationResult.succeeded(
        job=job,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
            WorkflowStage.ORIGINALITY_REVIEW,
            WorkflowStage.VOICE,
            WorkflowStage.ASSET_GENERATION,
            WorkflowStage.EDITING,
            WorkflowStage.QUALITY_CHECK,
            WorkflowStage.RENDER,
        ],
        elapsed_seconds=3.5,
    )

    assert result.success is True
    assert result.is_terminal is True
    assert result.is_failed is False
    assert result.is_cancelled is False

    assert result.render_result == render_result

    assert result.completed_stage_count == 8

    assert "completed successfully" in result.diagnostic_summary.lower()


def test_duplicate_stages_are_removed() -> None:
    job = build_job(
        status=JobStatus.FAILED,
        stage=WorkflowStage.RENDER,
    )

    result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.RENDER,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
            WorkflowStage.SCRIPT,
        ],
        elapsed_seconds=1.0,
        error_message="Failure.",
    )

    assert result.completed_stages == [
        WorkflowStage.RESEARCH,
        WorkflowStage.SCRIPT,
    ]


def test_messages_are_normalized() -> None:
    job = build_job(
        status=JobStatus.FAILED,
        stage=WorkflowStage.RENDER,
    )

    result = RenderOrchestrationResult(
        success=False,
        status=JobStatus.FAILED,
        current_stage=WorkflowStage.RENDER,
        completed_stages=[],
        failed_stage=WorkflowStage.RENDER,
        job=job,
        elapsed_seconds=1.0,
        warnings=[
            " Warning A ",
            "",
            "Warning A",
            "Warning B",
        ],
        errors=[
            " Failure ",
            "Failure",
        ],
    )

    assert result.warnings == [
        "Warning A",
        "Warning B",
    ]

    assert result.errors == [
        "Failure",
    ]


def test_serialization_round_trip() -> None:
    job = build_job(
        status=JobStatus.FAILED,
        stage=WorkflowStage.RENDER,
    )

    result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.RENDER,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
        ],
        elapsed_seconds=1.5,
        error_message="Failure.",
        metadata={
            "test": True,
        },
    )

    serialized = result.model_dump_json()

    restored = RenderOrchestrationResult.model_validate_json(serialized)

    assert restored == result


def main() -> None:
    print()
    print("Running Render Orchestration Result tests...")
    print()

    test_failed_result()
    test_cancelled_result()
    test_success_result()
    test_duplicate_stages_are_removed()
    test_messages_are_normalized()
    test_serialization_round_trip()

    print("Render Orchestration Result tests " "completed successfully.")


if __name__ == "__main__":
    main()
