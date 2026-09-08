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
from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig  # noqa: E402
from src.models.audience_promise import (  # noqa: E402
    AudiencePromise,
    PromiseStrength,
)
from src.models.content_decision_record import DecisionCategory  # noqa: E402
from src.models.enums import JobStatus, Platform, WorkflowStage  # noqa: E402
from src.models.final_export import FinalExportPackage, FinalExportStatus  # noqa: E402
from src.models.research import ResearchResult, ResearchStatus  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.script_lock import ScriptLock, ScriptProvenance  # noqa: E402
from src.models.seo import (  # noqa: E402
    SEOPackage,
    SEOPlatformMetadata,
    SEOStatus,
    TitleCandidate,
)
from src.models.thumbnail import (  # noqa: E402
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
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
