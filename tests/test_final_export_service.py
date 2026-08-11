from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.enums import JobStatus, Platform, WorkflowStage
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.final_export.final_export_service import (
    FinalExportBuildResult,
    FinalExportService,
)


def _seo_package() -> SEOPackage:
    return SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A complete, publish-ready description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )


def _thumbnail_artifact() -> ThumbnailArtifact:
    return ThumbnailArtifact(
        video_job_id=uuid4(),
        concept=ThumbnailConcept(
            concept_summary="A diver facing a giant squid.",
            hook_text="GIANT SQUID",
            visual_prompt="A deep sea diver facing a giant squid.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )


def _successful_render_orchestration_result(
    *,
    output_file: str | None = "outputs/final_video.mp4",
) -> RenderOrchestrationResult:
    job = VideoJob(
        project_name="Mission Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Render orchestration",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )

    job.research = ResearchResult.model_construct(status=ResearchStatus.APPROVED)

    job.script = Script(
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
        narration="Synthetic narration for orchestration testing.",
        visual_prompt="Synthetic visual prompt.",
        estimated_duration_seconds=30,
        manual_file_path="assets/videos/manual/test_scene.mp4",
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

    job.scenes = [scene]
    job.voice_file = "assets/audio/test_voice.wav"
    job.video_clips = [clip]

    job.video_timeline = VideoTimeline(clips=[clip])
    job.video_timeline.calculate_duration()

    job.audio_timeline = AudioTimeline()

    job.render_result = RenderResult(
        success=True,
        output_file=output_file,
        render_engine="ffmpeg",
        render_time_seconds=2.0,
        duration_seconds=30,
        status=RenderStatus.COMPLETED,
    )

    return RenderOrchestrationResult.succeeded(
        job=job,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
            WorkflowStage.RENDER,
        ],
        elapsed_seconds=3.5,
    )


def test_build_produces_a_final_export_package(tmp_path: Path) -> None:
    render_orchestration_result = _successful_render_orchestration_result()

    service = FinalExportService(export_root=tmp_path / "exports")

    result = service.build(
        render_orchestration_result,
        project_id="deep-sea-doc",
        resolution="1920x1080",
        frame_rate=30,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(),
    )

    assert isinstance(result, FinalExportBuildResult)
    assert result.package.duration_seconds == 30
    assert result.package.resolution == "1920x1080"
    assert result.package.video_job_id == render_orchestration_result.job.id


def test_build_raises_when_render_orchestration_failed(
    tmp_path: Path,
) -> None:
    job = VideoJob(
        project_name="Mission Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Render orchestration",
        status=JobStatus.FAILED,
        current_stage=WorkflowStage.RENDER,
    )

    failed_result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.RENDER,
        completed_stages=[],
        elapsed_seconds=1.0,
        error_message="Synthetic render failure.",
    )

    service = FinalExportService(export_root=tmp_path / "exports")

    with pytest.raises(ValueError, match="successful render orchestration"):
        service.build(
            failed_result,
            project_id="deep-sea-doc",
            resolution="1920x1080",
            frame_rate=30,
            seo_package=_seo_package(),
            thumbnail_artifact=_thumbnail_artifact(),
        )


def test_build_raises_when_render_result_has_no_output_file(
    tmp_path: Path,
) -> None:
    render_orchestration_result = _successful_render_orchestration_result(
        output_file=None,
    )

    service = FinalExportService(export_root=tmp_path / "exports")

    with pytest.raises(ValueError, match="output file"):
        service.build(
            render_orchestration_result,
            project_id="deep-sea-doc",
            resolution="1920x1080",
            frame_rate=30,
            seo_package=_seo_package(),
            thumbnail_artifact=_thumbnail_artifact(),
        )
