from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.enums import JobStatus, Platform, WorkflowStage
from src.models.final_export import FinalExportStatus
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.script_lock import ScriptLock, ScriptProvenance
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
from src.services.final_export.final_export_validation_service import (
    FinalExportValidationService,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
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


def test_build_marks_package_under_review_when_hard_qc_gates_fail(
    tmp_path: Path,
) -> None:
    missing_output_file = str(tmp_path / "definitely_missing_output.mp4")

    render_orchestration_result = _successful_render_orchestration_result(
        output_file=missing_output_file,
    )

    service = FinalExportService(export_root=tmp_path / "exports")

    result = service.build(
        render_orchestration_result,
        project_id="deep-sea-doc",
        resolution="1920x1080",
        frame_rate=30,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(),
    )

    assert result.validation.is_valid is False
    assert result.package.status == FinalExportStatus.UNDER_REVIEW

    assert result.package.manifest_path is not None
    with Path(result.package.manifest_path).open(encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["status"] == "under_review"


def test_build_marks_package_approved_when_hard_qc_gates_pass(
    tmp_path: Path,
) -> None:
    real_output_file = tmp_path / "final_video.mp4"
    real_output_file.write_bytes(b"fake rendered video bytes")

    render_orchestration_result = _successful_render_orchestration_result(
        output_file=str(real_output_file),
    )

    good_probe_output = (
        '{"format": {"duration": "30.0"}, '
        '"streams": ['
        '{"codec_type": "video", "width": 1920, "height": 1080}, '
        '{"codec_type": "audio"}'
        "]}"
    )

    validation_service = FinalExportValidationService(
        technical_validation_service=MediaTechnicalValidationService(
            runner=lambda _command: good_probe_output,
        ),
    )

    service = FinalExportService(
        export_root=tmp_path / "exports",
        validation_service=validation_service,
    )

    result = service.build(
        render_orchestration_result,
        project_id="deep-sea-doc",
        resolution="1920x1080",
        frame_rate=30,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(),
    )

    assert result.validation.is_valid is True
    assert result.package.status == FinalExportStatus.APPROVED

    assert result.package.manifest_path is not None
    with Path(result.package.manifest_path).open(encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["status"] == "approved"


def test_build_computes_production_provenance_from_the_job(
    tmp_path: Path,
) -> None:
    render_orchestration_result = _successful_render_orchestration_result()

    job = render_orchestration_result.job

    job.script_lock = ScriptLock(
        script_version_number=2,
        script_content_hash="deadbeef" * 4,
        provenance=ScriptProvenance.INTERNAL,
        topic=job.topic,
        target_duration_seconds=job.target_duration_seconds,
        genre_id=job.genre_id,
    )

    assert job.audio_timeline is not None

    job.audio_timeline.tracks = [
        AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file="assets/audio/test_voice.wav",
            duration_seconds=30.0,
            status=AudioTrackStatus.READY,
        ),
        AudioTrack(
            track_type=AudioTrackType.BACKGROUND_MUSIC,
            source_file="assets/audio/music.mp3",
            duration_seconds=30.0,
            status=AudioTrackStatus.READY,
        ),
    ]

    service = FinalExportService(export_root=tmp_path / "exports")

    result = service.build(
        render_orchestration_result,
        project_id="deep-sea-doc",
        resolution="1920x1080",
        frame_rate=30,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(),
    )

    provenance = result.package.provenance

    assert provenance is not None
    assert provenance.script_lock_hash == "deadbeef" * 4
    assert provenance.script_version_number == 2
    # The fixture's VideoTimeline is built with clips=[clip] directly,
    # not through TimelineBuilderService, so .items (explicit timeline
    # placements) stays empty here - this asserts the provenance
    # snapshot faithfully reflects that, not a guessed count.
    assert provenance.video_item_count == 0
    assert provenance.audio_track_count == 2
    assert provenance.voice_track_count == 1
    assert provenance.render_engine == "ffmpeg"
