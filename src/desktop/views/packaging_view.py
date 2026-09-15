from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    button,
    card,
    muted,
    small_muted,
    status_label,
    subheading,
)
from src.models.approval import ApprovalPolicy
from src.models.content_decision_record import DecisionCategory
from src.models.enums import Platform, WorkflowStage
from src.models.export_variant import ExportVariant, ExportVariantCollection
from src.models.final_export import FinalExportPackage
from src.models.seo import SEOPackage, SEOStatus
from src.models.specification_enums import AspectRatio
from src.models.thumbnail import ThumbnailArtifact, ThumbnailArtifactStatus
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.export_variant_render_service import ExportVariantRenderService
from src.services.final_export.final_export_service import FinalExportService
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.seo.seo_package_service import SEOPackageService
from src.services.thumbnail.thumbnail_package_service import ThumbnailPackageService

_ORIENTATION_LABELS: list[tuple[str, str]] = [
    ("Landscape (16:9)", AspectRatio.LANDSCAPE.value),
    ("Portrait (9:16)", AspectRatio.PORTRAIT.value),
]

# "" (not a real Platform value) represents "None" - a plain,
# optionally-reformatted export with no watermark/end-card CTA.
_PLATFORM_LABELS: list[tuple[str, str]] = [
    ("None", ""),
    ("YouTube", Platform.YOUTUBE.value),
    ("Facebook", Platform.FACEBOOK.value),
    ("TikTok", Platform.TIKTOK.value),
]

# YouTube and TikTok each have one dominant native shape, so picking
# either suggests (never forces) the matching orientation. Facebook is
# deliberately absent here - real Facebook video is genuinely bimodal
# (landscape feed posts vs. portrait Reels), and guessing wrong is
# worse than not guessing; its own row is left out entirely rather
# than mapped to some default, so the orientation dropdown is simply
# left untouched when Facebook is chosen.
_PLATFORM_ORIENTATION_SUGGESTION: dict[Platform, AspectRatio] = {
    Platform.YOUTUBE: AspectRatio.LANDSCAPE,
    Platform.TIKTOK: AspectRatio.PORTRAIT,
}

_LEFT = Qt.AlignmentFlag.AlignLeft


def _resolved_genre_id(job: VideoJob) -> str:
    """
    The genre identity SEO/thumbnail generation should describe.

    MRA-PRE-4 (Pre-Installer Master Audit, genre/audience/brand
    anti-drift audit) finding: `ScriptLock.genre_id` exists
    specifically to snapshot "topic, angle, target duration,
    genre/profile references" at the moment a script is frozen (see
    that model's own docstring), but had zero readers anywhere in the
    codebase - `job.genre_id` has no guard preventing a change after
    Script Lock (Content Studio's own "Project settings" card allows
    it freely), so SEO/thumbnail generation calling `build(...,
    genre_id=job.genre_id)` would silently describe a LOCKED script
    using a genre the script itself was never actually written in, if
    a person changed the project's genre after locking. Preferring the
    locked snapshot once one exists closes that gap; a lock with no
    genre_id (one built before this field existed) or no lock at all
    (SEO/thumbnail can be generated for a Script-Intake project with
    no lock) honestly falls back to the live field, matching every
    other optional-snapshot field's own established convention in this
    codebase.
    """

    if job.script_lock is not None and job.script_lock.genre_id is not None:
        return job.script_lock.genre_id

    return job.genre_id


def _script_is_approved(job: VideoJob) -> bool:
    """
    Whether this project has a finalized script ready to feed SEO/
    thumbnail generation.

    MRA-PRE-3 (Pre-Installer Master Audit) finding: this used to check
    only the legacy `job.script.status`, so both the SEO and thumbnail
    cards permanently showed "Requires an approved script." for every
    ContentIntelligencePipeline-produced project - that pipeline never
    populates `job.script`, only `job.generated_script` + `job.script_lock`
    once Script Lock happens. Script Lock is that pipeline's own hard
    "approved and frozen" boundary (see src/models/script_lock.py), the
    direct equivalent of `ScriptStatus.APPROVED` on the legacy field -
    mirrors the same reconciliation SEOContextBuilder.build() now does.
    """

    if job.generated_script is not None:
        return job.script_lock is not None

    return job.script is not None and job.script.status.value == "approved"


class _PackageProvenance(Protocol):
    """
    The dependency-tracking fields SEOPackage and ThumbnailArtifact
    both carry identically (Step 2, SEO-3/SEO-4) - a structural type
    so the staleness banner can accept either without depending on
    both concrete models or duplicating the check.
    """

    source_script_lock_hash: str | None
    source_genre_id: str | None
    source_target_country: str | None
    source_language: str | None
    source_scene_count: int | None


class PackagingView(QWidget):
    """
    Packaging: SEO metadata, thumbnail, and final publish-ready export.

    Final export only becomes available once a render actually
    succeeds, and requires both an SEO package and a thumbnail -
    building it any earlier would package an incomplete or missing
    video.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        final_export_service: FinalExportService,
        on_change: Callable[[], None],
        approval_gate_service: ApprovalGateService | None = None,
        export_variant_render_service: ExportVariantRenderService | None = None,
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._final_export_service = final_export_service
        self._on_change = on_change
        self._approval_gate_service = approval_gate_service or ApprovalGateService()
        self._export_variant_render_service = (
            export_variant_render_service or ExportVariantRenderService()
        )
        self._job_id: UUID | None = None

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content_container = QWidget()
        self._layout = QVBoxLayout(content_container)
        self._layout.setContentsMargins(0, 12, 4, 0)
        self._layout.setSpacing(16)

        scroll_area.setWidget(content_container)
        outer_layout.addWidget(scroll_area)

    def set_job(self, job_id: UUID) -> None:
        self._job_id = job_id

    def refresh(self, job: VideoJob) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_seo_card(job)
        self._build_thumbnail_card(job)
        self._build_export_variants_card(job)
        self._build_final_export_card(job)

    def _build_seo_card(self, job: VideoJob) -> None:
        frame, layout = card("SEO package", icon_name="tag")

        assert self._job_id is not None

        seo_package = self._job_store.get_seo_package(self._job_id)

        script_approved = _script_is_approved(job)

        if seo_package is not None:
            layout.addWidget(subheading(seo_package.selected_title or ""))
            layout.addWidget(muted(seo_package.description))
            layout.addWidget(small_muted(f"Tags: {', '.join(seo_package.tags)}"))
            layout.addWidget(small_muted(f"Hashtags: {' '.join(seo_package.hashtags)}"))
            layout.addWidget(
                small_muted(f"Version {seo_package.version_number}"),
            )

            self._build_dependency_staleness_banners(
                layout,
                job=job,
                provenance=seo_package,
            )

            self._build_review_status_row(
                layout,
                status_value=seo_package.status.value,
                on_approve=self._handle_approve_seo,
                on_reject=self._handle_reject_seo,
            )

            if script_approved:
                audience_getter = self._build_audience_widget(layout, job)

                regenerate_button = button("Regenerate SEO package", icon_name="tag")
                regenerate_button.clicked.connect(
                    lambda: self._handle_generate_seo(
                        audience_getter(),
                        previous_package=seo_package,
                    ),
                )
                layout.addWidget(regenerate_button, alignment=_LEFT)
        elif script_approved:
            layout.addWidget(small_muted("Not generated yet."))

            audience_getter = self._build_audience_widget(layout, job)

            generate_button = button(
                "Generate SEO package", variant="primary", icon_name="tag"
            )
            generate_button.clicked.connect(
                lambda: self._handle_generate_seo(audience_getter()),
            )
            layout.addWidget(generate_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires an approved script."))

        self._layout.addWidget(frame)

    def _build_thumbnail_card(self, job: VideoJob) -> None:
        frame, layout = card("Thumbnail", icon_name="image")

        assert self._job_id is not None

        thumbnail = self._job_store.get_thumbnail(self._job_id)

        script_approved = _script_is_approved(job)

        if thumbnail is not None:
            layout.addWidget(subheading(thumbnail.concept.hook_text))
            layout.addWidget(
                small_muted(f"Source: {thumbnail.image_source_type.value}")
            )
            layout.addWidget(small_muted(f"File: {thumbnail.file_path}"))
            layout.addWidget(
                small_muted(f"Version {thumbnail.version_number}"),
            )

            self._build_dependency_staleness_banners(
                layout,
                job=job,
                provenance=thumbnail,
            )

            self._build_review_status_row(
                layout,
                status_value=thumbnail.status.value,
                on_approve=self._handle_approve_thumbnail,
                on_reject=self._handle_reject_thumbnail,
            )

            if script_approved:
                audience_getter = self._build_audience_widget(layout, job)

                regenerate_button = button("Regenerate thumbnail", icon_name="image")
                regenerate_button.clicked.connect(
                    lambda: self._handle_generate_thumbnail(
                        audience_getter(),
                        previous_artifact=thumbnail,
                    ),
                )
                layout.addWidget(regenerate_button, alignment=_LEFT)
        elif script_approved:
            layout.addWidget(small_muted("Not generated yet."))

            audience_getter = self._build_audience_widget(layout, job)

            generate_button = button(
                "Generate thumbnail", variant="primary", icon_name="image"
            )
            generate_button.clicked.connect(
                lambda: self._handle_generate_thumbnail(audience_getter()),
            )
            layout.addWidget(generate_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires an approved script."))

        self._layout.addWidget(frame)

    @staticmethod
    def _build_audience_widget(
        layout: QVBoxLayout,
        job: VideoJob,
    ) -> Callable[[], str | None]:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-2:
        "Make publishing metadata consume canonical creative/audience
        authority without re-inference." When this project already
        has a canonical audience promise (Content Studio Redesign,
        Phase 6), show it read-only and let SEOContextBuilder resolve
        it automatically - no free-text box for a person to re-guess
        an audience the project has already established. Only a
        project with no audience promise (e.g. an imported Script
        Intake project) falls back to the original free-text entry.

        Returns a zero-argument getter rather than the resolved value
        directly, so a "Regenerate" button built once at refresh time
        still reads whatever is currently in the fallback box at the
        moment it's clicked.
        """

        if job.audience_promise is not None:
            layout.addWidget(
                small_muted(
                    "Target audience: "
                    f"{job.audience_promise.target_audience} "
                    "(from Audience & Creative Strategy)"
                )
            )

            return lambda: None

        audience_input = QLineEdit("General audience")
        layout.addWidget(audience_input)

        return audience_input.text

    @staticmethod
    def _build_dependency_staleness_banners(
        layout: QVBoxLayout,
        *,
        job: VideoJob,
        provenance: _PackageProvenance,
    ) -> None:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-4:
        "Define dependency graph for title, description, chapters,
        thumbnail copy, locale and final render duration... Material
        production changes must stale only affected publishing
        artifacts." A single script-content hash cannot catch every
        dependency this phase names - genre and locale can each
        change independently of the script's own text - so each
        tracked dependency is compared independently, naming exactly
        what moved rather than one coarse "something changed."

        Silent when nothing to compare against exists yet, or every
        tracked dependency still matches the job's current state.
        """

        if job.script_lock is not None:
            current_hash = job.script_lock.script_content_hash

            if provenance.source_script_lock_hash is None:
                layout.addWidget(
                    status_label(
                        "Built before the script was locked - "
                        "regenerate to bind it to the current script.",
                        role="warning",
                    )
                )
            elif provenance.source_script_lock_hash != current_hash:
                layout.addWidget(
                    status_label(
                        "Stale: the script has changed since this "
                        "was built. Regenerate to match the current "
                        "script.",
                        role="warning",
                    )
                )

        if (
            provenance.source_genre_id is not None
            and provenance.source_genre_id != job.genre_id
        ):
            layout.addWidget(
                status_label(
                    "Stale: the project's genre has changed since " "this was built.",
                    role="warning",
                )
            )

        if provenance.source_target_country is not None and (
            provenance.source_target_country != job.target_country
            or provenance.source_language != job.language
        ):
            layout.addWidget(
                status_label(
                    "Stale: the target country/language has changed "
                    "since this was built.",
                    role="warning",
                )
            )

        if (
            provenance.source_scene_count is not None
            and provenance.source_scene_count != len(job.scenes)
        ):
            layout.addWidget(
                status_label(
                    "Stale: the scene count has changed since this " "was built.",
                    role="warning",
                )
            )

    @staticmethod
    def _build_review_status_row(
        layout: QVBoxLayout,
        *,
        status_value: str,
        on_approve: Callable[[], None],
        on_reject: Callable[[], None],
    ) -> None:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-5:
        "Provide coherent review/approval card and history." Approving
        or rejecting here directly sets the package's own status - a
        deliberately simpler, more direct mechanism than routing
        through the generic cross-pipeline pending-decision banner
        elsewhere (Content Studio's Activity History), since a person
        is already looking at exactly the artifact in question. Every
        transition is still recorded to the same shared
        job.content_decisions ledger (see _handle_approve_seo etc.)
        for a unified audit trail - "shared audit primitives" without
        a second competing approval-state machine.
        """

        role = {"approved": "success", "rejected": "error"}.get(status_value, "warning")

        layout.addWidget(
            status_label(f"Review status: {status_value}", role=role),
        )

        if status_value != "under_review":
            return

        approve_button = button("Approve", variant="primary", icon_name="check")
        approve_button.clicked.connect(on_approve)
        layout.addWidget(approve_button, alignment=_LEFT)

        reject_button = button("Reject")
        reject_button.clicked.connect(on_reject)
        layout.addWidget(reject_button, alignment=_LEFT)

    def _build_export_variants_card(self, job: VideoJob) -> None:
        """
        Post-Script-Approval Production Plan, post-render export
        variants: reformat the already-rendered video into other
        orientations and/or brand it for a specific platform
        (watermark + 5s end-card CTA; platform-aware SEO/thumbnail
        packaging lands in a later phase) as a separate, lightweight
        pass, never a re-render of the timeline.
        """

        frame, layout = card("Export variants", icon_name="clapper")

        assert self._job_id is not None

        render_orchestration_result = self._job_store.get_render_result(self._job_id)
        render_result = (
            render_orchestration_result.render_result
            if render_orchestration_result is not None
            else None
        )

        if (
            render_orchestration_result is None
            or not render_orchestration_result.success
            or render_result is None
        ):
            layout.addWidget(
                small_muted("Requires a successful render (see Render Workspace).")
            )
            self._layout.addWidget(frame)

            return

        collection = self._job_store.get_export_variants(self._job_id)
        variants = collection.variants if collection is not None else []

        if not variants:
            layout.addWidget(small_muted("No export variants generated yet."))
        else:
            for variant in variants:
                platform_label = (
                    variant.platform.name.title() if variant.platform else "No CTA"
                )
                layout.addWidget(
                    small_muted(
                        f"{variant.orientation.name.title()} - {platform_label}: "
                        f"{variant.output_file}"
                    )
                )

                if variant.seo_package is not None:
                    layout.addWidget(
                        small_muted(
                            f"  SEO title: {variant.seo_package.selected_title}"
                        )
                    )

                if variant.thumbnail_artifact is not None:
                    layout.addWidget(
                        small_muted(
                            f"  Thumbnail: {variant.thumbnail_artifact.file_path}"
                        )
                    )

                self._build_variant_packaging_buttons(layout, variant)

                reveal_button = button(
                    f"Open output folder "
                    f"({variant.orientation.name.title()} - {platform_label})",
                    icon_name="folder",
                )
                reveal_button.clicked.connect(
                    lambda _checked=False, v=variant: self._handle_open_variant_folder(
                        v
                    ),
                )
                layout.addWidget(reveal_button, alignment=_LEFT)

        orientation_combo = QComboBox()

        for label, value in _ORIENTATION_LABELS:
            orientation_combo.addItem(label, userData=value)

        platform_combo = QComboBox()

        for label, value in _PLATFORM_LABELS:
            platform_combo.addItem(label, userData=value)

        platform_combo.currentIndexChanged.connect(
            lambda _index, o=orientation_combo, p=platform_combo: (
                self._handle_export_platform_changed(o, p)
            )
        )

        generate_button = button(
            "Generate variant",
            variant="primary",
            icon_name="clapper",
        )
        generate_button.clicked.connect(
            lambda: self._handle_generate_export_variant(
                orientation_combo, platform_combo
            )
        )

        layout.addWidget(small_muted("Orientation"))
        layout.addWidget(orientation_combo)
        layout.addWidget(small_muted("Platform"))
        layout.addWidget(platform_combo)
        layout.addWidget(generate_button, alignment=_LEFT)

        self._layout.addWidget(frame)

    def _build_variant_packaging_buttons(
        self,
        layout: QVBoxLayout,
        variant: ExportVariant,
    ) -> None:
        """
        Per-variant SEO/thumbnail packaging is optional and per-item,
        never a bundled hard requirement (see
        _handle_generate_variant_packaging's own docstring) - a
        variant with no platform has nothing platform-specific to
        generate at all; one with a platform shows a button for
        whichever piece(s) are still missing, and a person can click
        any combination of them, or none, and leave the variant as a
        plain branded/reformatted video with no packaging attached.
        """

        if variant.platform is None:
            return

        missing_seo = variant.seo_package is None
        missing_thumbnail = variant.thumbnail_artifact is None

        if not missing_seo and not missing_thumbnail:
            return

        # Deliberately distinct from the job-level SEO/Thumbnail cards'
        # own "Generate SEO package"/"Generate thumbnail" buttons (real
        # bug found live: identical text made a naive find-by-text
        # click land on the wrong button, silently updating the job's
        # own shared package instead of this variant's) - also
        # disambiguates between multiple variants' own buttons, same
        # "(orientation - platform)" convention this card's own reveal
        # button already uses.
        variant_label = (
            f"{variant.orientation.name.title()} - {variant.platform.name.title()}"
        )

        if missing_seo and missing_thumbnail:
            generate_all_button = button(
                f"Generate all packaging ({variant_label})",
                icon_name="tag",
            )
            generate_all_button.clicked.connect(
                lambda _checked=False, v=variant: (
                    self._handle_generate_variant_packaging(
                        v, generate_seo=True, generate_thumbnail=True
                    )
                )
            )
            layout.addWidget(generate_all_button, alignment=_LEFT)

        if missing_seo:
            generate_seo_button = button(
                f"Generate SEO package ({variant_label})",
                icon_name="tag",
            )
            generate_seo_button.clicked.connect(
                lambda _checked=False, v=variant: (
                    self._handle_generate_variant_packaging(
                        v, generate_seo=True, generate_thumbnail=False
                    )
                )
            )
            layout.addWidget(generate_seo_button, alignment=_LEFT)

        if missing_thumbnail:
            generate_thumbnail_button = button(
                f"Generate thumbnail ({variant_label})",
                icon_name="image",
            )
            generate_thumbnail_button.clicked.connect(
                lambda _checked=False, v=variant: (
                    self._handle_generate_variant_packaging(
                        v, generate_seo=False, generate_thumbnail=True
                    )
                )
            )
            layout.addWidget(generate_thumbnail_button, alignment=_LEFT)

    def _build_final_export_card(self, job: VideoJob) -> None:
        frame, layout = card("Final export", icon_name="export")

        assert self._job_id is not None

        final_export = self._job_store.get_final_export(self._job_id)
        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if final_export is not None:
            status_role = (
                "success" if final_export.status.value == "approved" else "warning"
            )

            layout.addWidget(
                status_label(f"Status: {final_export.status.value}", role=status_role)
            )
            layout.addWidget(small_muted(f"Video: {final_export.final_video_path}"))
            layout.addWidget(
                small_muted(f"Export directory: {final_export.export_directory}")
            )

            self._build_qc_summary(layout, final_export)

            actions_row_widgets: list[QWidget] = []

            open_folder_button = button(
                "Open output folder",
                icon_name="folder",
            )
            open_folder_button.clicked.connect(
                lambda: self._handle_open_output_folder(final_export),
            )
            actions_row_widgets.append(open_folder_button)

            if final_export.manifest_path is not None:
                copy_manifest_button = button(
                    "Copy manifest path",
                )
                copy_manifest_button.clicked.connect(
                    lambda: self._handle_copy_manifest_path(final_export),
                )
                actions_row_widgets.append(copy_manifest_button)

            for action_widget in actions_row_widgets:
                layout.addWidget(action_widget, alignment=_LEFT)

            # MRA-PRE-6 (Pre-Installer Master Audit, publishing/package
            # audit) finding: WorkflowStage.UPLOADED is a real, defined
            # terminal stage - VideoJob's own dashboard/list views
            # already display job.current_stage.value directly - but
            # nothing anywhere in the codebase ever wrote it. There is
            # no real, automated "publish to platform" integration
            # (confirmed: no YouTube/platform upload code exists in
            # this repository), so publishing is always a manual,
            # external step - this is the corresponding manual
            # closing-the-loop action, exactly like a real "Mark as
            # uploaded" checkbox once a person has actually done that
            # themselves. Only offered once the package has passed
            # hard QC (approved) - marking an under-review package
            # published would misrepresent readiness.
            if (
                final_export.status.value == "approved"
                and job.current_stage != WorkflowStage.UPLOADED
            ):
                mark_uploaded_button = button(
                    "Mark as published",
                    icon_name="check",
                )
                mark_uploaded_button.clicked.connect(self._handle_mark_as_uploaded)
                layout.addWidget(mark_uploaded_button, alignment=_LEFT)
            elif job.current_stage == WorkflowStage.UPLOADED:
                layout.addWidget(status_label("Published.", role="success"))
        elif render_result is not None and render_result.success:
            if seo_package is not None and thumbnail is not None:
                layout.addWidget(small_muted("Not built yet."))

                export_button = button(
                    "Build final export package",
                    variant="primary",
                    icon_name="export",
                )
                export_button.clicked.connect(self._handle_build_final_export)
                layout.addWidget(export_button, alignment=_LEFT)
            else:
                layout.addWidget(
                    small_muted("Requires an SEO package and a thumbnail."),
                )
        else:
            layout.addWidget(
                small_muted("Requires a successful render (see Render Workspace).")
            )

        self._layout.addWidget(frame)

    def _build_qc_summary(
        self,
        layout: QVBoxLayout,
        final_export: FinalExportPackage,
    ) -> None:
        """
        Show the Final Package screen's QC summary.

        Re-runs the same, cheap, deterministic (no LLM/network calls)
        validation the build step already ran, so the summary always
        reflects the package's current on-disk state rather than a
        stale snapshot from whenever it was last built.
        """

        validation = self._final_export_service.validation_service.validate(
            final_export
        )

        if validation.is_valid and not validation.has_warnings:
            layout.addWidget(status_label("QC: all checks passed.", role="success"))
            return

        for issue in validation.errors:
            layout.addWidget(status_label(f"QC error: {issue.message}", role="error"))

        for issue in validation.warnings:
            layout.addWidget(
                status_label(f"QC warning: {issue.message}", role="warning")
            )

    def _handle_open_output_folder(
        self,
        final_export: FinalExportPackage,
    ) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(final_export.export_directory),
        )

    def _handle_export_platform_changed(
        self, orientation_combo: QComboBox, platform_combo: QComboBox
    ) -> None:
        """
        A one-click convenience, never a hard constraint - picking
        YouTube or TikTok suggests (overwrites) the orientation
        dropdown to that platform's one dominant native shape; picking
        Facebook or None leaves the orientation dropdown exactly as it
        was, since Facebook video is genuinely bimodal (landscape feed
        posts vs. portrait Reels) and guessing wrong is worse than not
        guessing. Every combination stays manually reachable regardless.
        """

        platform = self._read_platform(platform_combo)

        if platform is None:
            return

        suggested_orientation = _PLATFORM_ORIENTATION_SUGGESTION.get(platform)

        if suggested_orientation is None:
            return

        index = orientation_combo.findData(suggested_orientation.value)

        if index >= 0:
            orientation_combo.setCurrentIndex(index)

    def _handle_generate_export_variant(
        self, orientation_combo: QComboBox, platform_combo: QComboBox
    ) -> None:
        job = self._current_job()

        if job is None or self._job_id is None:
            return

        render_orchestration_result = self._job_store.get_render_result(self._job_id)
        render_result = (
            render_orchestration_result.render_result
            if render_orchestration_result is not None
            else None
        )

        if render_result is None:
            return

        # Real-world finding, 2026-09-14: a QComboBox's userData round-
        # trips a plain string reliably through PySide6's QVariant
        # marshalling, but NOT an AspectRatio enum member directly
        # (confirmed live - a real test's isinstance(data, AspectRatio)
        # check silently failed after a real .currentData() call,
        # never even reaching this handler's own service call). The
        # combo stores AspectRatio.value strings (see
        # _ORIENTATION_LABELS); converted back here.
        orientation_value = orientation_combo.currentData()

        if not isinstance(orientation_value, str):
            return

        try:
            orientation = AspectRatio(orientation_value)
        except ValueError:
            return

        platform = self._read_platform(platform_combo)

        try:
            variant = self._export_variant_render_service.build(
                job=job,
                render_result=render_result,
                orientation=orientation,
                platform=platform,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Export variant generation failed: {error}",
                on_retry=lambda: self._handle_generate_export_variant(
                    orientation_combo, platform_combo
                ),
            )

            return

        existing = self._job_store.get_export_variants(self._job_id)
        variants = list(existing.variants) if existing is not None else []
        variants.append(variant)

        self._job_store.set_export_variants(
            self._job_id, ExportVariantCollection(variants=variants)
        )

        self._on_change()

    def _handle_generate_variant_packaging(
        self,
        variant: ExportVariant,
        *,
        generate_seo: bool,
        generate_thumbnail: bool,
    ) -> None:
        """
        Post-render export variant packaging (SEO package, thumbnail)
        is optional and per-item, never a bundled hard requirement - a
        variant with a real platform can be left with no packaging at
        all, get only one piece, or get both, driven entirely by which
        of this card's own "Generate all packaging" / "Generate SEO
        package" / "Generate thumbnail" buttons a person clicks. Never
        called for a platform=None variant (there is nothing
        platform-specific to generate).

        Builds a fresh SEOPackage/ThumbnailArtifact with the variant's
        own platform as an explicit override - never the job's single
        shared SEOPackage/ThumbnailArtifact (see SEOContextBuilder.
        build()'s own docstring for why this never mutates the job's
        own primary platform). Mirrors _handle_generate_seo/
        _handle_generate_thumbnail's own call shape exactly, just keyed
        to the variant's platform instead of the job's default one.
        """

        job = self._current_job()

        if job is None or self._job_id is None or variant.platform is None:
            return

        platform = variant.platform
        updated = variant

        try:
            if generate_seo:
                seo_result = self._seo_package_service.build(
                    job,
                    genre_id=_resolved_genre_id(job),
                    platform=platform,
                )
                updated = updated.model_copy(
                    update={"seo_package": seo_result.package},
                )

            if generate_thumbnail:
                context = SEOContextBuilder().build(
                    job,
                    genre_id=_resolved_genre_id(job),
                    platform=platform,
                )
                thumbnail_result = self._thumbnail_package_service.build(
                    context,
                    project_id=job.project_name,
                )
                updated = updated.model_copy(
                    update={"thumbnail_artifact": thumbnail_result.artifact},
                )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Export variant packaging failed: {error}",
                on_retry=lambda: self._handle_generate_variant_packaging(
                    variant,
                    generate_seo=generate_seo,
                    generate_thumbnail=generate_thumbnail,
                ),
            )

            return

        existing = self._job_store.get_export_variants(self._job_id)
        variants = list(existing.variants) if existing is not None else []
        variants = [updated if v.id == variant.id else v for v in variants]

        self._job_store.set_export_variants(
            self._job_id, ExportVariantCollection(variants=variants)
        )

        self._on_change()

    @staticmethod
    def _read_platform(platform_combo: QComboBox) -> Platform | None:
        """
        Same plain-string userData convention as the orientation combo
        (see _handle_generate_export_variant's own real-world-finding
        comment) - "" (not a real Platform value) represents "None".
        """

        platform_value = platform_combo.currentData()

        if not isinstance(platform_value, str) or not platform_value:
            return None

        try:
            return Platform(platform_value)
        except ValueError:
            return None

    def _handle_open_variant_folder(self, variant: ExportVariant) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(variant.output_file).parent)),
        )

    def _handle_copy_manifest_path(
        self,
        final_export: FinalExportPackage,
    ) -> None:
        if final_export.manifest_path is None:
            return

        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(final_export.manifest_path)

    def _handle_mark_as_uploaded(self) -> None:
        """
        Close the loop on WorkflowStage.UPLOADED (MRA-PRE-6 finding) -
        record that a person has actually published this project's
        final export externally. There is no real, automated publish
        integration in this codebase, so this is a manual
        acknowledgement, not a trigger for any upload itself.
        """

        job = self._current_job()

        if job is None or self._job_id is None:
            return

        final_export = self._job_store.get_final_export(self._job_id)

        if final_export is None or final_export.status.value != "approved":
            return

        job.current_stage = WorkflowStage.UPLOADED

        self._approval_gate_service.record_event(
            job=job,
            stage="final_export",
            summary="Project marked as published.",
            category=DecisionCategory.APPROVAL,
        )

        self._on_change()

    def _handle_generate_seo(
        self,
        target_audience: str | None,
        *,
        previous_package: SEOPackage | None = None,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            result = self._seo_package_service.build(
                job,
                genre_id=_resolved_genre_id(job),
                target_audience=target_audience,
                previous_package=previous_package,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"SEO generation failed: {error}",
                on_retry=lambda: self._handle_generate_seo(
                    target_audience,
                    previous_package=previous_package,
                ),
            )

            return

        assert self._job_id is not None

        package = result.package

        if job.approval_policy.policy_for("publishing") == ApprovalPolicy.AUTO:
            package = package.model_copy(update={"status": SEOStatus.APPROVED})

        self._approval_gate_service.record_event(
            job=job,
            stage="seo",
            summary=(f"SEO package generated (version {package.version_number})."),
            category=DecisionCategory.GENERATION,
        )

        self._job_store.set_seo_package(self._job_id, package)
        self._on_change()

    def _handle_approve_seo(self) -> None:
        self._resolve_seo_review(SEOStatus.APPROVED, "approved")

    def _handle_reject_seo(self) -> None:
        self._resolve_seo_review(SEOStatus.REJECTED, "rejected")

    def _resolve_seo_review(
        self,
        status: SEOStatus,
        verb: str,
    ) -> None:
        job = self._current_job()

        if job is None or self._job_id is None:
            return

        package = self._job_store.get_seo_package(self._job_id)

        if package is None:
            return

        resolved = package.model_copy(update={"status": status})

        self._approval_gate_service.record_event(
            job=job,
            stage="seo",
            summary=f"SEO package {verb}.",
            category=DecisionCategory.APPROVAL,
        )

        self._job_store.set_seo_package(self._job_id, resolved)
        self._on_change()

    def _handle_generate_thumbnail(
        self,
        target_audience: str | None,
        *,
        previous_artifact: ThumbnailArtifact | None = None,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            context = SEOContextBuilder().build(
                job,
                genre_id=_resolved_genre_id(job),
                target_audience=target_audience,
            )

            result = self._thumbnail_package_service.build(
                context,
                project_id=job.project_name,
                previous_artifact=previous_artifact,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Thumbnail generation failed: {error}",
                on_retry=lambda: self._handle_generate_thumbnail(
                    target_audience,
                    previous_artifact=previous_artifact,
                ),
            )

            return

        assert self._job_id is not None

        artifact = result.artifact

        if job.approval_policy.policy_for("publishing") == ApprovalPolicy.AUTO:
            artifact = artifact.model_copy(
                update={"status": ThumbnailArtifactStatus.APPROVED},
            )

        self._approval_gate_service.record_event(
            job=job,
            stage="thumbnail",
            summary=(f"Thumbnail generated (version {artifact.version_number})."),
            category=DecisionCategory.GENERATION,
        )

        self._job_store.set_thumbnail(self._job_id, artifact)
        self._on_change()

    def _handle_approve_thumbnail(self) -> None:
        self._resolve_thumbnail_review(ThumbnailArtifactStatus.APPROVED, "approved")

    def _handle_reject_thumbnail(self) -> None:
        self._resolve_thumbnail_review(ThumbnailArtifactStatus.REJECTED, "rejected")

    def _resolve_thumbnail_review(
        self,
        status: ThumbnailArtifactStatus,
        verb: str,
    ) -> None:
        job = self._current_job()

        if job is None or self._job_id is None:
            return

        artifact = self._job_store.get_thumbnail(self._job_id)

        if artifact is None:
            return

        resolved = artifact.model_copy(update={"status": status})

        self._approval_gate_service.record_event(
            job=job,
            stage="thumbnail",
            summary=f"Thumbnail {verb}.",
            category=DecisionCategory.APPROVAL,
        )

        self._job_store.set_thumbnail(self._job_id, resolved)
        self._on_change()

    def _handle_build_final_export(self) -> None:
        job = self._current_job()

        if job is None:
            return

        assert self._job_id is not None

        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if render_result is None or seo_package is None or thumbnail is None:
            return

        try:
            result = self._final_export_service.build(
                render_result,
                project_id=job.project_name,
                resolution=job.output_resolution,
                frame_rate=30,
                seo_package=seo_package,
                thumbnail_artifact=thumbnail,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Final export failed: {error}",
                on_retry=self._handle_build_final_export,
            )

            return

        self._job_store.set_final_export(self._job_id, result.package)
        self._on_change()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    def _record_error(
        self,
        job: VideoJob,
        message: str,
        *,
        on_retry: Callable[[], None] | None = None,
    ) -> None:
        job.errors.append(message)
        show_recoverable_error(self, "Step failed", message, on_retry=on_retry)
        self._on_change()
