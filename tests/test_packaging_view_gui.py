from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
)

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.audience_promise import (  # noqa: E402
    AudiencePromise,
    PromiseStrength,
)
from src.models.enums import JobStatus, Platform, WorkflowStage  # noqa: E402
from src.models.final_export import FinalExportPackage, FinalExportStatus  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.script_lock import ScriptLock, ScriptProvenance  # noqa: E402
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


def _job_with_approved_script() -> VideoJob:
    job = VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )
    job.script = Script(
        title="Giant Squid Encounter",
        content="Narration about a giant squid encounter.",
        prompt_version="script_prompt_v1.0.0",
        estimated_duration_seconds=300,
        status=ScriptStatus.APPROVED,
    )

    return job


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


def test_seo_card_shows_version_and_regenerate_button(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(job.id, _seo_package())

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    buttons = [button.text() for button in view.findChildren(QPushButton)]

    assert any("Version 1" in text for text in labels)
    assert "Regenerate SEO package" in buttons
    assert "Generate SEO package" not in buttons


def test_seo_card_shows_staleness_banner_when_script_lock_hash_mismatches(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()
    job.script_lock = ScriptLock(
        script_version_number=2,
        script_content_hash="current-hash",
        provenance=ScriptProvenance.INTERNAL,
    )

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(
            update={"source_script_lock_hash": "old-hash"},
        ),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("Stale:" in text for text in labels)


def test_seo_card_no_staleness_banner_when_hashes_match(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()
    job.script_lock = ScriptLock(
        script_version_number=2,
        script_content_hash="current-hash",
        provenance=ScriptProvenance.INTERNAL,
    )

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(
            update={"source_script_lock_hash": "current-hash"},
        ),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert not any("Stale:" in text for text in labels)
    assert not any("Built before the script was locked" in text for text in labels)


def test_seo_card_shows_unlocked_banner_when_package_predates_the_lock(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()
    job.script_lock = ScriptLock(
        script_version_number=1,
        script_content_hash="current-hash",
        provenance=ScriptProvenance.INTERNAL,
    )

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(job.id, _seo_package())

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("Built before the script was locked" in text for text in labels)


def test_thumbnail_card_shows_version_and_regenerate_button(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_thumbnail(job.id, _thumbnail_artifact())

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    buttons = [button.text() for button in view.findChildren(QPushButton)]

    assert any("Version 1" in text for text in labels)
    assert "Regenerate thumbnail" in buttons
    assert "Generate thumbnail" not in buttons


def test_seo_card_shows_canonical_audience_and_no_free_text_box_when_promised(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()
    job.audience_promise = AudiencePromise(
        topic="Giant squid",
        target_audience="Deep sea documentary fans",
        platform="youtube",
        genre_id="genre.documentary",
        target_duration_seconds=300,
        intended_emotion="wonder",
        central_curiosity="What is down there?",
        primary_question="What is down there?",
        viewer_benefit="A close look at a giant squid.",
        expected_payoff="Understanding giant squid behavior.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )

    view._job_store.add(job)
    view.set_job(job.id)

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    line_edits = view.findChildren(QLineEdit)

    assert any("Deep sea documentary fans" in text for text in labels)
    assert not any(edit.text() == "General audience" for edit in line_edits)


def test_seo_card_shows_free_text_audience_box_without_a_promise(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)

    view.refresh(job)

    line_edits = view.findChildren(QLineEdit)

    assert any(edit.text() == "General audience" for edit in line_edits)
