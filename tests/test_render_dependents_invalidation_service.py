"""
A new successful render makes the export variants and final export that
were built from the previous render stale. Real-world finding,
2026-10-03: re-rendering (e.g. with subtitles turned off) left the old
variants and final export on the Packaging tab as if they were current.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore, JobStore, JsonJobStore  # noqa: E402
from src.desktop.views.render_workspace_view import (  # noqa: E402
    RenderWorkspaceView,
    _RenderWorker,
)
from src.models.audio_timeline import AudioTimeline  # noqa: E402
from src.models.enums import JobStatus, Platform, WorkflowStage  # noqa: E402
from src.models.export_variant import (  # noqa: E402
    ExportVariant,
    ExportVariantCollection,
)
from src.models.final_export import FinalExportPackage  # noqa: E402
from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus  # noqa: E402
from src.models.research import ResearchResult, ResearchStatus  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.seo import (  # noqa: E402
    SEOPackage,
    SEOPlatformMetadata,
    TitleCandidate,
)
from src.models.specification_enums import AspectRatio  # noqa: E402
from src.models.thumbnail import (  # noqa: E402
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.video_clip import VideoClip  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.video_timeline import VideoTimeline  # noqa: E402
from src.services.render_dependents_invalidation_service import (  # noqa: E402
    RERENDER_NOTICE,
    invalidate_render_dependents,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )


def _seo(job: VideoJob) -> SEOPackage:
    return SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )


def _thumbnail(job: VideoJob) -> ThumbnailArtifact:
    return ThumbnailArtifact(
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


def _final_export(job: VideoJob) -> FinalExportPackage:
    return FinalExportPackage(
        video_job_id=job.id,
        project_id="Test Project",
        final_video_path="data/final_exports/test_project/video.mp4",
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=60,
        seo_package=_seo(job),
        thumbnail_artifact=_thumbnail(job),
        export_directory="data/final_exports/test_project",
    )


def _variants() -> ExportVariantCollection:
    return ExportVariantCollection(
        variants=[
            ExportVariant(
                orientation=AspectRatio.PORTRAIT,
                platform=Platform.FACEBOOK,
                output_file="outputs/final_video_portrait_facebook.mp4",
            )
        ]
    )


def _populated(store: JobStore) -> VideoJob:
    job = _job()
    store.add(job)
    store.set_seo_package(job.id, _seo(job))
    store.set_thumbnail(job.id, _thumbnail(job))
    store.set_export_variants(job.id, _variants())
    store.set_final_export(job.id, _final_export(job))

    return job


def test_clears_variants_and_final_export_but_keeps_seo_and_thumbnail() -> None:
    store = InMemoryJobStore()
    job = _populated(store)

    cleared = invalidate_render_dependents(store, job, job.id)

    assert cleared == ["export variants", "final export"]
    assert store.get_export_variants(job.id) is None
    assert store.get_final_export(job.id) is None
    # Neither depends on the rendered video.
    assert store.get_seo_package(job.id) is not None
    assert store.get_thumbnail(job.id) is not None


def test_records_one_notice_on_the_job_even_if_repeated() -> None:
    store = InMemoryJobStore()
    job = _populated(store)

    invalidate_render_dependents(store, job, job.id)
    store.set_export_variants(job.id, _variants())
    invalidate_render_dependents(store, job, job.id)

    assert job.warnings.count(RERENDER_NOTICE) == 1


def test_nothing_stale_means_nothing_cleared_and_no_notice() -> None:
    store = InMemoryJobStore()
    job = _job()
    store.add(job)

    assert invalidate_render_dependents(store, job, job.id) == []
    assert job.warnings == []


def test_an_empty_variant_collection_is_not_reported_as_cleared() -> None:
    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    store.set_export_variants(job.id, ExportVariantCollection(variants=[]))

    assert invalidate_render_dependents(store, job, job.id) == []


def test_clearing_persists_across_a_fresh_json_store(tmp_path: Path) -> None:
    """The records must stay gone after a restart, not just in the cache."""

    store = JsonJobStore(storage_root=tmp_path)
    job = _populated(store)

    invalidate_render_dependents(store, job, job.id)

    fresh = JsonJobStore(storage_root=tmp_path)

    assert fresh.get_export_variants(job.id) is None
    assert fresh.get_final_export(job.id) is None
    assert fresh.get_seo_package(job.id) is not None


def test_clear_methods_are_idempotent_and_leave_exported_files_alone(
    tmp_path: Path,
) -> None:
    exported = tmp_path / "video.mp4"
    exported.write_bytes(b"the operator's deliverable")

    store = JsonJobStore(storage_root=tmp_path / "store")
    job = _populated(store)

    store.clear_export_variants(job.id)
    store.clear_export_variants(job.id)
    store.clear_final_export(job.id)
    store.clear_final_export(job.id)
    store.clear_final_export(_job().id)

    assert exported.read_bytes() == b"the operator's deliverable"


def _rendered_job() -> tuple[VideoJob, RenderOrchestrationResult]:
    job = _job()
    job.research = ResearchResult(
        topic="Test topic",
        research_summary="Summary.",
        prompt_version="test-1.0",
        status=ResearchStatus.APPROVED,
    )
    job.script = Script(
        title="Test script",
        content="Synthetic script content.",
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=20,
        status=ScriptStatus.APPROVED,
    )
    job.scenes = [
        Scene(
            scene_number=1,
            title="Scene 1",
            narration="Narration.",
            visual_prompt="Visual.",
            estimated_duration_seconds=8,
        )
    ]
    job.voice_file = "dry-run://voice/test.mp3"
    job.audio_timeline = AudioTimeline()
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=8,
            local_file="/data/manual_uploads/scene_1.mp4",
        )
    ]
    job.video_timeline = VideoTimeline()
    render = RenderResult(
        success=True,
        output_file="outputs/final_video.mp4",
        render_engine="ffmpeg",
        duration_seconds=60,
        status=RenderStatus.COMPLETED,
    )
    job.render_result = render
    job.status = JobStatus.COMPLETED
    job.current_stage = WorkflowStage.READY_FOR_UPLOAD

    result = RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=render,
    )

    return job, result


def _finish_a_render(
    view: RenderWorkspaceView, job: VideoJob, result: RenderOrchestrationResult
) -> None:
    """Drive the real _handle_render_finished through a real worker, the
    way a finished background render does (it reads self.sender())."""

    worker = _RenderWorker(
        orchestrator=object(),  # type: ignore[arg-type]
        job=job,
        user_input=None,
    )
    worker.finished.connect(view._handle_render_finished)
    worker.finished.emit(result)


def _view_for(store: JobStore, job: VideoJob) -> RenderWorkspaceView:
    view = RenderWorkspaceView(
        job_store=store,
        render_runtime_factory=object(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )
    view.set_job(job.id)

    return view


def test_a_finished_render_clears_the_stale_variants_and_export(
    qapp: QApplication,
) -> None:
    store = InMemoryJobStore()
    job, result = _rendered_job()
    store.add(job)
    store.set_export_variants(job.id, _variants())
    store.set_final_export(job.id, _final_export(job))

    _finish_a_render(_view_for(store, job), job, result)

    assert store.get_render_result(job.id) is result
    assert store.get_export_variants(job.id) is None
    assert store.get_final_export(job.id) is None
    assert RERENDER_NOTICE in job.warnings


def test_a_failed_render_leaves_existing_variants_alone(qapp: QApplication) -> None:
    """A failed render replaces nothing on disk (output is staged then
    promoted), so what was built from the last good render is still true."""

    store = InMemoryJobStore()
    job, _ok = _rendered_job()
    store.add(job)
    store.set_export_variants(job.id, _variants())

    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.ASSET_GENERATION
    failed = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.ASSET_GENERATION,
        completed_stages=[],
        elapsed_seconds=0.1,
        error_message="No matching local asset was found.",
    )

    _finish_a_render(_view_for(store, job), job, failed)

    assert store.get_export_variants(job.id) is not None
    assert RERENDER_NOTICE not in job.warnings
