from __future__ import annotations

from uuid import uuid4

from src.desktop.job_store import InMemoryJobStore
from src.models.enums import JobStatus, Platform, WorkflowStage
from src.models.final_export import FinalExportPackage
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.video_job import VideoJob


def _job(project_name: str = "Test Project") -> VideoJob:
    return VideoJob(
        project_name=project_name,
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )


def test_add_and_get_job() -> None:
    store = InMemoryJobStore()
    job = _job()

    store.add(job)

    assert store.get(job.id) is job


def test_get_returns_none_for_unknown_job() -> None:
    store = InMemoryJobStore()

    assert store.get(uuid4()) is None


def test_list_all_returns_newest_first() -> None:
    store = InMemoryJobStore()

    first = _job("First")
    second = _job("Second")

    store.add(first)
    store.add(second)

    jobs = store.list_all()

    assert [job.project_name for job in jobs] == ["Second", "First"]


def test_seo_package_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert store.get_seo_package(job.id) is None

    store.set_seo_package(job.id, seo_package)

    assert store.get_seo_package(job.id) is seo_package


def test_thumbnail_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )

    assert store.get_thumbnail(job.id) is None

    store.set_thumbnail(job.id, thumbnail)

    assert store.get_thumbnail(job.id) is thumbnail


def test_render_result_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()
    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.ASSET_GENERATION

    render_result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.ASSET_GENERATION,
        completed_stages=[],
        elapsed_seconds=0.1,
        error_message="No matching local asset was found.",
    )

    assert store.get_render_result(job.id) is None

    store.set_render_result(job.id, render_result)

    assert store.get_render_result(job.id) is render_result


def test_final_export_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )

    final_export = FinalExportPackage(
        video_job_id=job.id,
        project_id="Test Project",
        final_video_path="data/final_exports/test_project/video.mp4",
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=60,
        seo_package=seo_package,
        thumbnail_artifact=thumbnail,
        export_directory="data/final_exports/test_project",
    )

    assert store.get_final_export(job.id) is None

    store.set_final_export(job.id, final_export)

    assert store.get_final_export(job.id) is final_export
