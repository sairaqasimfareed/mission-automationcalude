from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
)

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig  # noqa: E402
from src.models.audience_promise import (  # noqa: E402
    AudiencePromise,
    PromiseStrength,
)
from src.models.content_decision_record import DecisionCategory  # noqa: E402
from src.models.enums import JobStatus, Platform, WorkflowStage  # noqa: E402
from src.models.export_variant import (  # noqa: E402
    ExportVariant,
    ExportVariantCollection,
)
from src.models.final_export import FinalExportPackage, FinalExportStatus  # noqa: E402
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus  # noqa: E402
from src.models.research import ResearchResult, ResearchStatus  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.script_lock import ScriptLock, ScriptProvenance  # noqa: E402
from src.models.seo import (  # noqa: E402
    SEOPackage,
    SEOPlatformMetadata,
    SEOStatus,
    TitleCandidate,
)
from src.models.specification_enums import AspectRatio  # noqa: E402
from src.models.thumbnail import (  # noqa: E402
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.thumbnail_validation import ThumbnailValidationResult  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.final_export.final_export_service import (  # noqa: E402
    FinalExportService,
)
from src.services.llm.llm_service import LLMServiceResult  # noqa: E402
from src.services.seo.seo_description_generation_service import (  # noqa: E402
    SEODescriptionGenerationService,
)
from src.services.seo.seo_package_service import SEOPackageService  # noqa: E402
from src.services.seo.seo_title_generation_service import (  # noqa: E402
    SEOTitleGenerationService,
)
from src.services.thumbnail.thumbnail_package_service import (  # noqa: E402
    ThumbnailPackageBuildResult,
)
from src.shared.llm.models import (  # noqa: E402
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
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


def test_final_export_card_shows_mark_as_published_when_approved(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """
    MRA-PRE-6 (Pre-Installer Master Audit, publishing/package audit)
    finding: `WorkflowStage.UPLOADED` was a real, defined terminal
    stage with no code path anywhere that ever wrote it - a project
    stayed at `READY_FOR_UPLOAD` forever, even after a person actually
    published it, with no way to close the loop. Proves the fix: an
    approved final export now offers a "Mark as published" action.
    """

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

    approved_export = _final_export_package(
        manifest_path=str(manifest_file),
    ).model_copy(update={"status": FinalExportStatus.APPROVED})

    view._job_store.set_final_export(job.id, approved_export)

    view.refresh(job)

    buttons = [button_widget.text() for button_widget in view.findChildren(QPushButton)]

    assert "Mark as published" in buttons


def test_mark_as_uploaded_sets_the_terminal_workflow_stage(
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

    approved_export = _final_export_package(
        manifest_path=str(manifest_file),
    ).model_copy(update={"status": FinalExportStatus.APPROVED})

    view._job_store.set_final_export(job.id, approved_export)

    view._handle_mark_as_uploaded()

    assert job.current_stage == WorkflowStage.UPLOADED
    assert any(
        record.stage == "final_export" and record.category == DecisionCategory.APPROVAL
        for record in job.content_decisions
    )


def test_mark_as_uploaded_is_a_no_op_when_export_is_not_approved(
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

    under_review_export = _final_export_package(manifest_path=str(manifest_file))
    assert under_review_export.status == FinalExportStatus.UNDER_REVIEW

    view._job_store.set_final_export(job.id, under_review_export)

    view._handle_mark_as_uploaded()

    assert job.current_stage == WorkflowStage.READY_FOR_UPLOAD


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
        topic=job.topic,
        target_duration_seconds=job.target_duration_seconds,
        genre_id=job.genre_id,
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
        topic=job.topic,
        target_duration_seconds=job.target_duration_seconds,
        genre_id=job.genre_id,
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
        topic=job.topic,
        target_duration_seconds=job.target_duration_seconds,
        genre_id=job.genre_id,
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


def test_seo_card_shows_staleness_banner_when_genre_changed(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()
    job.genre_id = "genre.horror"

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(update={"source_genre_id": "genre.documentary"}),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("genre has changed" in text for text in labels)


def test_seo_card_shows_staleness_banner_when_locale_changed(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()
    job.target_country = "Canada"

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(
            update={
                "source_target_country": "United States",
                "source_language": "English",
            }
        ),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("target country/language has changed" in text for text in labels)


def test_seo_card_shows_staleness_banner_when_scene_count_changed(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(update={"source_scene_count": 5}),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("scene count has changed" in text for text in labels)


def test_seo_card_shows_no_dependency_staleness_when_everything_matches(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(
            update={
                "source_genre_id": job.genre_id,
                "source_target_country": job.target_country,
                "source_language": job.language,
                "source_scene_count": len(job.scenes),
            }
        ),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert not any("has changed since this was built" in text for text in labels)


def test_seo_card_shows_approve_reject_buttons_when_under_review(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(update={"status": SEOStatus.UNDER_REVIEW}),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    buttons = [button.text() for button in view.findChildren(QPushButton)]

    assert any("Review status: under_review" in text for text in labels)
    assert "Approve" in buttons
    assert "Reject" in buttons


def test_seo_card_hides_approve_reject_buttons_when_already_approved(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(update={"status": SEOStatus.APPROVED}),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    buttons = [button.text() for button in view.findChildren(QPushButton)]

    assert any("Review status: approved" in text for text in labels)
    assert "Approve" not in buttons
    assert "Reject" not in buttons


def test_approve_seo_flips_status_and_records_audit_event(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(update={"status": SEOStatus.UNDER_REVIEW}),
    )

    view._handle_approve_seo()

    updated = view._job_store.get_seo_package(job.id)

    assert updated is not None
    assert updated.status == SEOStatus.APPROVED
    assert any(
        record.stage == "seo" and record.category == DecisionCategory.APPROVAL
        for record in job.content_decisions
    )


def test_reject_seo_flips_status(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id,
        _seo_package().model_copy(update={"status": SEOStatus.UNDER_REVIEW}),
    )

    view._handle_reject_seo()

    updated = view._job_store.get_seo_package(job.id)

    assert updated is not None
    assert updated.status == SEOStatus.REJECTED


def test_approve_thumbnail_flips_status_and_records_audit_event(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_thumbnail(
        job.id,
        _thumbnail_artifact().model_copy(
            update={"status": ThumbnailArtifactStatus.UNDER_REVIEW},
        ),
    )

    view._handle_approve_thumbnail()

    updated = view._job_store.get_thumbnail(job.id)

    assert updated is not None
    assert updated.status == ThumbnailArtifactStatus.APPROVED
    assert any(
        record.stage == "thumbnail" and record.category == DecisionCategory.APPROVAL
        for record in job.content_decisions
    )


class _StubTitleDescriptionLLMService:
    """Minimal stub covering only the two LLM calls SEOPackageService.build() makes."""

    def generate(
        self,
        request: object,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        prompt_version = getattr(request, "prompt_version", "")

        if prompt_version == "seo_title_prompt_v1.0.0":
            content = "Giant Squid Encounter Explained"
        else:
            content = "A close encounter with a giant squid in the deep sea."

        return LLMServiceResult(
            result=LLMCallResult(
                status=LLMCallStatus.SUCCESS,
                provider=LLMProvider.OPENAI,
                model="test-model",
                content=content,
            ),
            selected_profile_id="openai-main",
        )


def _real_seo_package_service() -> SEOPackageService:
    stub = _StubTitleDescriptionLLMService()

    return SEOPackageService(
        title_generation_service=SEOTitleGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
        ),
        description_generation_service=SEODescriptionGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
        ),
    )


def test_generate_seo_auto_approves_when_publishing_policy_is_auto(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=_real_seo_package_service(),
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
    )

    job = _job_with_approved_script()
    job.approval_policy = ApprovalPolicyConfig(publishing=ApprovalPolicy.AUTO)
    job.research = ResearchResult(
        topic="Giant squid",
        research_summary="An overview of giant squid encounters.",
        key_facts=["Fact one."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )

    view._job_store.add(job)
    view.set_job(job.id)

    view._handle_generate_seo("Ocean enthusiasts")

    package = view._job_store.get_seo_package(job.id)

    assert package is not None
    assert package.status == SEOStatus.APPROVED
    assert any(
        record.stage == "seo" and record.category == DecisionCategory.GENERATION
        for record in job.content_decisions
    )


def test_generate_seo_stays_under_review_by_default_policy(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=_real_seo_package_service(),
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
    )

    job = _job_with_approved_script()
    job.research = ResearchResult(
        topic="Giant squid",
        research_summary="An overview of giant squid encounters.",
        key_facts=["Fact one."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )

    view._job_store.add(job)
    view.set_job(job.id)

    view._handle_generate_seo("Ocean enthusiasts")

    package = view._job_store.get_seo_package(job.id)

    assert package is not None
    assert package.status == SEOStatus.UNDER_REVIEW


def test_generate_seo_uses_the_locked_genre_not_a_later_changed_one(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """
    MRA-PRE-4 (Pre-Installer Master Audit, genre/audience/brand
    anti-drift audit) finding: `job.genre_id` has no guard preventing
    a change after Script Lock (Content Studio's "Project settings"
    card allows it freely), so SEO generation calling `build(...,
    genre_id=job.genre_id)` would silently describe a LOCKED script
    using a genre the script itself was never written in. Proves the
    fix: SEO generation now prefers the genre snapshotted on
    `job.script_lock` at lock time over a later, live change.
    """

    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=_real_seo_package_service(),
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
    )

    job = _job_with_approved_script()
    job.research = ResearchResult(
        topic="Giant squid",
        research_summary="An overview of giant squid encounters.",
        key_facts=["Fact one."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )
    job.script_lock = ScriptLock(
        script_version_number=1,
        script_content_hash="locked-hash",
        provenance=ScriptProvenance.INTERNAL,
        topic=job.topic,
        target_duration_seconds=job.target_duration_seconds,
        genre_id="genre.documentary",
    )

    # A person changes the project's genre in "Project settings" AFTER
    # the script was already locked in genre.documentary - the script
    # text itself does not change, only the live field.
    job.genre_id = "genre.horror"

    view._job_store.add(job)
    view.set_job(job.id)

    view._handle_generate_seo("Ocean enthusiasts")

    package = view._job_store.get_seo_package(job.id)

    assert package is not None
    assert package.source_genre_id == "genre.documentary"


def test_thumbnail_card_does_not_crash_when_file_is_missing(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """
    Step 2, SEO-9: "corrupt/missing thumbnail" recovery. The card only
    ever displays the stored file_path as text - it never touches the
    filesystem to render a preview - so a thumbnail whose file has
    since been deleted or moved must still refresh cleanly rather than
    raising or leaving the card half-built.
    """

    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_thumbnail(
        job.id,
        _thumbnail_artifact().model_copy(
            update={
                "file_path": str(tmp_path / "this_file_does_not_exist.png"),
            },
        ),
    )

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("this_file_does_not_exist.png" in text for text in labels)


def _bare_job() -> VideoJob:
    """
    A minimal, valid VideoJob with no script/research - export variant
    generation only needs a successful render result, and
    RenderOrchestrationResult's own cross-field validator rejects a
    job with a script but no research (a real, unrelated invariant
    _job_with_approved_script()'s job would trip).
    """

    return VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )


def _render_orchestration_result(
    job: VideoJob, *, output_file: str = "F:/renders/job1/output.mp4"
) -> RenderOrchestrationResult:
    return RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=RenderResult(
            success=True,
            status=RenderStatus.COMPLETED,
            output_file=output_file,
            render_engine="ffmpeg",
            duration_seconds=60,
        ),
    )


class _FakeExportVariantRenderService:
    def __init__(self) -> None:
        self.build_calls: list[tuple[AspectRatio, Platform | None]] = []

    def build(
        self,
        *,
        job: VideoJob,
        render_result: RenderResult,
        orientation: AspectRatio,
        platform: Platform | None = None,
        progress_callback: object = None,
        cancellation_check: object = None,
    ) -> ExportVariant:
        self.build_calls.append((orientation, platform))

        suffix_parts = []
        if orientation == AspectRatio.PORTRAIT:
            suffix_parts.append("portrait")
        if platform is not None:
            suffix_parts.append(platform.value)
        suffix = ("_" + "_".join(suffix_parts)) if suffix_parts else ""

        return ExportVariant(
            orientation=orientation,
            platform=platform,
            output_file=f"F:/renders/job1/output{suffix}.mp4",
        )


class _FakeThumbnailPackageService:
    """
    Records the platform each build() call used and returns a canned
    artifact - skips real image generation (no ThumbnailImageProvider
    is wired in these tests), which is irrelevant to what this file
    actually verifies: that _handle_generate_variant_packaging calls
    through with the variant's own platform, not the job's default
    one.
    """

    def __init__(self) -> None:
        self.build_calls: list[Platform] = []

    def build(
        self,
        context: object,
        *,
        project_id: str,
        **_kwargs: object,
    ) -> ThumbnailPackageBuildResult:
        self.build_calls.append(context.platform)  # type: ignore[attr-defined]

        return ThumbnailPackageBuildResult(
            artifact=_thumbnail_artifact(),
            validation=ThumbnailValidationResult(is_valid=True),
        )


def _wait_for_variant_generation(
    view: PackagingView, qapp: QApplication, *, timeout_seconds: float = 30.0
) -> None:
    """
    "Generate variant" now runs on a background QThread and returns
    immediately (real-world finding, 2026-10-01: the previous
    synchronous version froze the whole app, reported by Windows as
    "Not Responding", for the length of a real FFmpeg pass) - tests
    asserting on its outcome must pump the Qt event loop until the
    worker's queued finished/failed and thread.finished signals have
    actually been delivered.
    """

    deadline = time.monotonic() + timeout_seconds

    while view._export_variant_threads or view._generating_export_variant_job_ids:
        if time.monotonic() > deadline:
            raise TimeoutError("Export variant generation never completed.")

        qapp.processEvents()
        time.sleep(0.01)

    assert view.wait_for_pending_generations(timeout_ms=10_000)


def _platform_combo(view: PackagingView) -> QComboBox:
    """
    Find the export-variants card's platform combo by its real content
    rather than raw findChildren() order - the packaging view also renders
    the title-card position combo, which shifts positional indices.
    """

    return next(
        combo
        for combo in view.findChildren(QComboBox)
        if combo.itemText(0) == "YouTube"
    )


def test_export_variants_card_requires_a_successful_render(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _job_with_approved_script()

    view._job_store.add(job)
    view.set_job(job.id)

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("Requires a successful render" in text for text in labels)


def test_export_variants_card_shows_no_variants_yet(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(export_root=tmp_path / "exports")
    job = _bare_job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))

    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]
    buttons = [button.text() for button in view.findChildren(QPushButton)]

    assert any("No export variants generated yet" in text for text in labels)
    assert "Generate variant" in buttons


def test_generate_export_variant_stores_the_result(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeExportVariantRenderService()
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        export_variant_render_service=fake_service,  # type: ignore[arg-type]
    )
    job = _bare_job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view.refresh(job)

    platform_combo = _platform_combo(view)
    platform_combo.setCurrentIndex(platform_combo.findData(Platform.YOUTUBE.value))

    generate_button = next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Generate variant"
    )
    generate_button.click()
    _wait_for_variant_generation(view, qapp)

    assert fake_service.build_calls == [(AspectRatio.LANDSCAPE, Platform.YOUTUBE)]

    stored = view._job_store.get_export_variants(job.id)
    assert stored is not None
    assert len(stored.variants) == 1
    assert stored.variants[0].orientation == AspectRatio.LANDSCAPE
    assert stored.variants[0].output_file == "F:/renders/job1/output_youtube.mp4"


def test_generate_export_variant_appends_to_existing_variants(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeExportVariantRenderService()
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        export_variant_render_service=fake_service,  # type: ignore[arg-type]
    )
    job = _bare_job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view._job_store.set_export_variants(
        job.id,
        ExportVariantCollection(
            variants=[
                ExportVariant(
                    orientation=AspectRatio.LANDSCAPE,
                    output_file="F:/renders/job1/output.mp4",
                )
            ]
        ),
    )
    view.refresh(job)

    platform_combo = _platform_combo(view)
    platform_combo.setCurrentIndex(platform_combo.findData(Platform.TIKTOK.value))

    generate_button = next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Generate variant"
    )
    generate_button.click()
    _wait_for_variant_generation(view, qapp)

    stored = view._job_store.get_export_variants(job.id)
    assert stored is not None
    assert len(stored.variants) == 2
    assert [v.platform for v in stored.variants] == [None, Platform.TIKTOK]


def _view_with_render_result(
    tmp_path: Path, fake_service: _FakeExportVariantRenderService
) -> tuple[PackagingView, VideoJob]:
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        export_variant_render_service=fake_service,  # type: ignore[arg-type]
    )
    job = _bare_job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view.refresh(job)

    return view, job


def test_there_is_no_orientation_choice_and_no_none_platform(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The Orientation dropdown was removed (2026-10-08): a variant is always the
    project's own shape, so there is nothing to choose and nothing to re-apply to a video
    that was rendered in the right shape already."""

    view, _job = _view_with_render_result(tmp_path, _FakeExportVariantRenderService())

    first_items = [combo.itemText(0) for combo in view.findChildren(QComboBox)]
    labels = [label.text() for label in view.findChildren(QLabel)]

    assert "Landscape (16:9)" not in first_items
    assert not any(label == "Orientation" for label in labels)
    assert [
        _platform_combo(view).itemText(i) for i in range(_platform_combo(view).count())
    ] == ["YouTube", "Facebook", "TikTok"]
    assert any("Shape: Landscape (16:9)" in label for label in labels)


def test_a_vertical_project_says_so_and_makes_vertical_variants(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeExportVariantRenderService()
    view, job = _view_with_render_result(tmp_path, fake_service)
    job.aspect_ratio = AspectRatio.PORTRAIT
    view.refresh(job)

    assert any(
        "Shape: Portrait (9:16)" in label.text() for label in view.findChildren(QLabel)
    )

    platform_combo = _platform_combo(view)
    platform_combo.setCurrentIndex(platform_combo.findData(Platform.TIKTOK.value))
    next(
        b for b in view.findChildren(QPushButton) if b.text() == "Generate variant"
    ).click()
    _wait_for_variant_generation(view, qapp)

    assert fake_service.build_calls == [(AspectRatio.PORTRAIT, Platform.TIKTOK)]


def test_a_landscape_project_makes_landscape_variants_for_every_platform(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeExportVariantRenderService()
    view, _job = _view_with_render_result(tmp_path, fake_service)

    for platform in (Platform.YOUTUBE, Platform.FACEBOOK, Platform.TIKTOK):
        combo = _platform_combo(view)
        combo.setCurrentIndex(combo.findData(platform.value))
        next(
            b for b in view.findChildren(QPushButton) if b.text() == "Generate variant"
        ).click()
        _wait_for_variant_generation(view, qapp)

    assert [o for o, _p in fake_service.build_calls] == [AspectRatio.LANDSCAPE] * 3


def test_the_projects_master_orientation_follows_its_shape() -> None:
    job = _bare_job()

    assert job.master_orientation == AspectRatio.LANDSCAPE

    job.aspect_ratio = AspectRatio.PORTRAIT

    assert job.master_orientation == AspectRatio.PORTRAIT


def test_generate_export_variant_passes_the_chosen_platform_through(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Generating a variant is purely the FFmpeg reformat/watermark/CTA
    pass - picking a platform no longer forces SEO/thumbnail
    generation as a bundled side effect (that is now a separate,
    opt-in step - see test_generate_all_packaging_button_builds_seo_
    and_thumbnail_for_the_variant below). seo_package_service=None is
    deliberately passed here to prove this path never touches it.
    """

    fake_service = _FakeExportVariantRenderService()
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        export_variant_render_service=fake_service,  # type: ignore[arg-type]
    )
    job = _bare_job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view.refresh(job)

    platform_combo = _platform_combo(view)
    platform_combo.setCurrentIndex(platform_combo.findData(Platform.FACEBOOK.value))

    generate_button = next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Generate variant"
    )
    generate_button.click()
    _wait_for_variant_generation(view, qapp)

    assert fake_service.build_calls == [(AspectRatio.LANDSCAPE, Platform.FACEBOOK)]

    stored = view._job_store.get_export_variants(job.id)
    assert stored is not None
    assert stored.variants[0].platform == Platform.FACEBOOK
    assert stored.variants[0].seo_package is None
    assert stored.variants[0].thumbnail_artifact is None


def _view_with_facebook_variant(
    tmp_path: Path,
    *,
    seo_package_service: SEOPackageService | None,
    thumbnail_package_service: object,
) -> tuple[PackagingView, VideoJob]:
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=seo_package_service,  # type: ignore[arg-type]
        thumbnail_package_service=thumbnail_package_service,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        export_variant_render_service=(
            _FakeExportVariantRenderService()  # type: ignore[arg-type]
        ),
    )
    job = _job_with_approved_script()
    job.research = ResearchResult(
        topic="Giant squid",
        research_summary="An overview of giant squid encounters.",
        key_facts=["Fact one."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )
    # SEOContextBuilder.build() requires a resolvable target audience
    # (from the job's own audience promise, or an explicit override
    # this handler never supplies - see _handle_generate_variant_
    # packaging) - without one it raises ValueError, which
    # _record_error() routes to a real QMessageBox.exec() that blocks
    # forever under headless Qt (confirmed live: a first version of
    # this helper omitted audience_promise and hung every test that
    # clicked a packaging button).
    job.audience_promise = AudiencePromise(
        topic="Giant squid",
        target_audience="Deep sea documentary fans",
        platform="facebook",
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
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view._job_store.set_export_variants(
        job.id,
        ExportVariantCollection(
            variants=[
                ExportVariant(
                    orientation=AspectRatio.LANDSCAPE,
                    platform=Platform.FACEBOOK,
                    output_file="F:/renders/job1/output_facebook.mp4",
                ),
            ]
        ),
    )
    view.refresh(job)

    return view, job


def test_variant_list_offers_generate_all_packaging_when_both_pieces_are_missing(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job = _view_with_facebook_variant(
        tmp_path,
        seo_package_service=_real_seo_package_service(),
        thumbnail_package_service=_FakeThumbnailPackageService(),
    )

    button_labels = [widget.text() for widget in view.findChildren(QPushButton)]

    assert "Generate all packaging (Landscape - Facebook)" in button_labels
    assert "Generate SEO package (Landscape - Facebook)" in button_labels
    assert "Generate thumbnail (Landscape - Facebook)" in button_labels


def test_generate_all_packaging_button_builds_seo_and_thumbnail_for_the_variant(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_thumbnail_service = _FakeThumbnailPackageService()
    view, job = _view_with_facebook_variant(
        tmp_path,
        seo_package_service=_real_seo_package_service(),
        thumbnail_package_service=fake_thumbnail_service,
    )

    generate_all_button = next(
        widget
        for widget in view.findChildren(QPushButton)
        if widget.text() == "Generate all packaging (Landscape - Facebook)"
    )
    generate_all_button.click()

    assert fake_thumbnail_service.build_calls == [Platform.FACEBOOK]

    stored = view._job_store.get_export_variants(job.id)
    assert stored is not None
    assert stored.variants[0].seo_package is not None
    assert stored.variants[0].seo_package.platform_metadata.platform == (
        Platform.FACEBOOK
    )
    assert stored.variants[0].thumbnail_artifact is not None


def test_generate_seo_package_button_leaves_thumbnail_untouched(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_thumbnail_service = _FakeThumbnailPackageService()
    view, job = _view_with_facebook_variant(
        tmp_path,
        seo_package_service=_real_seo_package_service(),
        thumbnail_package_service=fake_thumbnail_service,
    )

    generate_seo_button = next(
        widget
        for widget in view.findChildren(QPushButton)
        if widget.text() == "Generate SEO package (Landscape - Facebook)"
    )
    generate_seo_button.click()

    assert fake_thumbnail_service.build_calls == []

    stored = view._job_store.get_export_variants(job.id)
    assert stored is not None
    assert stored.variants[0].seo_package is not None
    assert stored.variants[0].thumbnail_artifact is None


def test_variant_with_full_packaging_offers_no_packaging_buttons(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        export_variant_render_service=(
            _FakeExportVariantRenderService()  # type: ignore[arg-type]
        ),
    )
    job = _bare_job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view._job_store.set_export_variants(
        job.id,
        ExportVariantCollection(
            variants=[
                ExportVariant(
                    orientation=AspectRatio.LANDSCAPE,
                    platform=Platform.FACEBOOK,
                    output_file="F:/renders/job1/output_facebook.mp4",
                    seo_package=_seo_package(),
                    thumbnail_artifact=_thumbnail_artifact(),
                ),
            ]
        ),
    )
    view.refresh(job)

    button_labels = [widget.text() for widget in view.findChildren(QPushButton)]

    assert not any("Generate all packaging" in label for label in button_labels)
    assert not any("Generate SEO package" in label for label in button_labels)
    assert not any("Generate thumbnail" in label for label in button_labels)


def test_variant_list_shows_no_cta_for_a_platformless_variant(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _view_with_render_result(tmp_path, _FakeExportVariantRenderService())

    view._job_store.set_export_variants(
        job.id,
        ExportVariantCollection(
            variants=[
                ExportVariant(
                    orientation=AspectRatio.LANDSCAPE,
                    platform=None,
                    output_file="F:/renders/job1/output.mp4",
                )
            ]
        ),
    )
    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("No CTA" in text for text in labels)


class _BlockingExportVariantRenderService:
    """Blocks inside build() until released or cancelled."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.saw_cancellation = False

    def build(
        self,
        *,
        job: VideoJob,
        render_result: RenderResult,
        orientation: AspectRatio,
        platform: Platform | None = None,
        progress_callback: object = None,
        cancellation_check: object = None,
    ) -> ExportVariant:
        assert callable(progress_callback)
        assert callable(cancellation_check)

        self.started.set()
        deadline = time.monotonic() + 20.0

        while time.monotonic() < deadline:
            if cancellation_check():
                self.saw_cancellation = True

                # Real service contract: a cancelled FFmpeg pass raises.
                raise RuntimeError("FFmpeg render was cancelled.")

            if self.release.is_set():
                break

            time.sleep(0.01)

        return ExportVariant(
            orientation=orientation,
            platform=platform,
            output_file="F:/renders/job1/output.mp4",
        )


def _blocking_variant_view(
    tmp_path: Path,
) -> tuple[PackagingView, VideoJob, _BlockingExportVariantRenderService]:
    service = _BlockingExportVariantRenderService()
    job = _bare_job()
    holder: dict[str, PackagingView] = {}

    # Mirrors the real app: on_change refreshes the workspace, which is
    # what restores the controls once a generation ends.
    view = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: holder["view"].refresh(job),
        export_variant_render_service=service,  # type: ignore[arg-type]
    )
    holder["view"] = view

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_render_result(job.id, _render_orchestration_result(job))
    view.refresh(job)

    return view, job, service


def _variant_buttons(view: PackagingView) -> dict[str, QPushButton]:
    return {b.text(): b for b in view.findChildren(QPushButton)}


def _wait_until_true(qapp: QApplication, predicate: object) -> None:
    deadline = time.monotonic() + 10.0

    while not predicate():  # type: ignore[operator]
        if time.monotonic() > deadline:
            raise TimeoutError("Condition never became true.")

        qapp.processEvents()
        time.sleep(0.01)


def test_export_variant_runs_in_the_background_with_progress_and_stop(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Real-world finding, 2026-10-01: the user saw the app go "Not
    Responding" for the length of a real export-variant FFmpeg pass,
    blocking every other action. The click must return immediately,
    swapping the controls for a progress state with a Stop button.
    """

    view, job, service = _blocking_variant_view(tmp_path)

    _variant_buttons(view)["Generate variant"].click()

    # The worker is still blocked inside build() here - reaching this
    # line at all proves the handler did not run the pass synchronously.
    assert job.id in view._generating_export_variant_job_ids
    # Old widgets are only queued for deletion by the rebuild - flush
    # so findChildren() reflects what the user actually sees.
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    buttons = _variant_buttons(view)
    assert "Generate variant" not in buttons
    assert "Stop" in buttons
    assert view._export_variant_progress_bar.value() == 0

    _wait_until_true(qapp, service.started.is_set)
    service.release.set()
    _wait_for_variant_generation(view, qapp)

    stored = view._job_store.get_export_variants(job.id)
    assert stored is not None
    assert len(stored.variants) == 1
    assert "Generate variant" in _variant_buttons(view)


def test_stopping_an_export_variant_records_no_variant_and_restores_controls(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job, service = _blocking_variant_view(tmp_path)

    _variant_buttons(view)["Generate variant"].click()
    _wait_until_true(qapp, service.started.is_set)

    with patch("src.desktop.views.packaging_view.show_recoverable_error"):
        _variant_buttons(view)["Stop"].click()
        _wait_for_variant_generation(view, qapp)

    assert service.saw_cancellation
    assert job.id not in view._generating_export_variant_job_ids

    stored = view._job_store.get_export_variants(job.id)
    assert stored is None or stored.variants == []
    # Restart is simply clicking Generate variant again.
    assert "Generate variant" in _variant_buttons(view)


def _cta_displays(view: PackagingView) -> tuple[QLineEdit, QLineEdit]:
    watermark = next(
        edit
        for edit in view.findChildren(QLineEdit)
        if edit.placeholderText() == "Default: generated text watermark"
    )
    clip = next(
        edit
        for edit in view.findChildren(QLineEdit)
        if edit.placeholderText() == "Default: generated 5s text end-card"
    )

    return watermark, clip


def _button(view: PackagingView, text: str) -> QPushButton:
    # The Export variants card sits below the title card, which has its
    # own "Upload my own image..." button - the last match is the one
    # under test.
    return [b for b in view.findChildren(QPushButton) if b.text() == text][-1]


def _refresh_and_flush(view: PackagingView, job: VideoJob, qapp: QApplication) -> None:
    view.refresh(job)
    # Rebuilt cards' old widgets linger in findChildren() until Qt's
    # deferred deletes are delivered.
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_cta_upload_fields_default_to_empty_so_generated_defaults_apply(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _view_with_render_result(tmp_path, _FakeExportVariantRenderService())

    watermark, clip = _cta_displays(view)

    assert watermark.text() == ""
    assert clip.text() == ""
    assert job.cta_watermark_image_path is None
    assert job.cta_end_clip_path is None


def test_uploading_and_saving_persists_both_cta_paths(
    qapp: QApplication, tmp_path: Path
) -> None:
    on_change_calls: list[bool] = []
    view, job = _view_with_render_result(tmp_path, _FakeExportVariantRenderService())
    view._on_change = lambda: on_change_calls.append(True)

    with patch(
        "src.desktop.views.packaging_view.QFileDialog.getOpenFileName",
        side_effect=[("C:/brand/logo.png", ""), ("C:/brand/cta.mp4", "")],
    ):
        _button(view, "Upload my own image...").click()
        _button(view, "Upload my own clip...").click()

    # Nothing is persisted until "Save CTA settings" - same as title card.
    assert job.cta_watermark_image_path is None
    assert job.cta_end_clip_path is None

    _button(view, "Save CTA settings").click()

    assert job.cta_watermark_image_path == "C:/brand/logo.png"
    assert job.cta_end_clip_path == "C:/brand/cta.mp4"
    assert on_change_calls == [True]


def test_cancelling_the_file_dialog_keeps_the_existing_cta_value(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _view_with_render_result(tmp_path, _FakeExportVariantRenderService())
    job.cta_end_clip_path = "C:/brand/cta.mp4"
    _refresh_and_flush(view, job, qapp)

    with patch(
        "src.desktop.views.packaging_view.QFileDialog.getOpenFileName",
        return_value=("", ""),
    ):
        _button(view, "Upload my own clip...").click()

    assert _cta_displays(view)[1].text() == "C:/brand/cta.mp4"


def test_remove_then_save_returns_to_the_generated_defaults(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _view_with_render_result(tmp_path, _FakeExportVariantRenderService())
    job.cta_watermark_image_path = "C:/brand/logo.png"
    job.cta_end_clip_path = "C:/brand/cta.mp4"
    _refresh_and_flush(view, job, qapp)

    # Export variants' two "Remove" buttons are the last two on screen.
    for remove in [b for b in view.findChildren(QPushButton) if b.text() == "Remove"][
        -2:
    ]:
        remove.click()

    _button(view, "Save CTA settings").click()

    assert job.cta_watermark_image_path is None
    assert job.cta_end_clip_path is None
