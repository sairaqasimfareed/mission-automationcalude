from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.enums import JobStatus, Platform, WorkflowStage  # noqa: E402
from src.models.final_export import FinalExportPackage, FinalExportStatus  # noqa: E402
from src.models.seo import (  # noqa: E402
    SEOPackage,
    SEOPlatformMetadata,
    TitleCandidate,
)
from src.models.thumbnail import (  # noqa: E402
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.video_job import VideoJob  # noqa: E402
from src.services.final_export.final_export_service import (  # noqa: E402
    FinalExportService,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


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


def _final_export_package(*, manifest_path: str) -> FinalExportPackage:
    return FinalExportPackage(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_path="dry-run://render/output.mp4",
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(),
        export_directory="exports/deep-sea-doc",
        manifest_path=manifest_path,
        status=FinalExportStatus.UNDER_REVIEW,
    )


def _view(*, export_root: Path) -> PackagingView:
    return PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=export_root),
        on_change=lambda: None,
    )


def test_final_export_card_shows_qc_summary_and_actions(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    view = _view(export_root=tmp_path / "exports")

    job = VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )

    view._job_store.add(job)
    view.set_job(job.id)

    final_export = _final_export_package(manifest_path=str(manifest_file))
    view._job_store.set_final_export(job.id, final_export)

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    buttons = [button.text() for button in view.findChildren(QPushButton)]

    assert any("Status: under_review" in text for text in labels)
    assert any("QC warning:" in text for text in labels)
    assert "Open output folder" in buttons
    assert "Copy manifest path" in buttons


def test_final_export_card_shows_all_checks_passed_when_clean(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    view = _view(export_root=tmp_path / "exports")

    job = VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )

    view._job_store.add(job)
    view.set_job(job.id)

    final_export = _final_export_package(
        manifest_path=str(manifest_file),
    ).model_copy(
        update={
            "status": FinalExportStatus.APPROVED,
            "seo_package": _seo_package().model_copy(update={"status": "approved"}),
            "thumbnail_artifact": _thumbnail_artifact().model_copy(
                update={"status": "approved"},
            ),
        },
    )

    view._job_store.set_final_export(job.id, final_export)

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("QC: all checks passed." in text for text in labels)
