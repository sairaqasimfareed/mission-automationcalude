from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.scroll_preservation import keep_scroll_on_refresh
from src.desktop.widgets import (
    button,
    card,
    muted,
    row,
    small_muted,
    status_label,
    subheading,
)
from src.models.approval import ApprovalPolicy
from src.models.content_decision_record import DecisionCategory
from src.models.enums import Platform, WorkflowStage
from src.models.export_variant import ExportVariant, ExportVariantCollection
from src.models.final_export import FinalExportPackage
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.render_progress import RenderProgress
from src.models.render_result import RenderResult
from src.models.seo import SEOPackage, SEOStatus
from src.models.specification_enums import AspectRatio
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailTextPosition,
)
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.export_variant_render_service import ExportVariantRenderService
from src.services.final_export.final_export_service import FinalExportService
from src.services.opening_title_card_service import OpeningTitleCardService
from src.services.render_result_resolution_service import (
    replace_orchestration_render_result,
    resolve_effective_render_orchestration_result,
    resolve_effective_render_result,
)
from src.services.seo.seo_context_builder import SEOContext, SEOContextBuilder
from src.services.seo.seo_package_service import SEOPackageService
from src.services.subtitle_burn_action_service import SubtitleBurnActionService
from src.services.subtitle_burn_targets import (
    SubtitleBurnTarget,
    subtitle_burn_targets,
)
from src.services.thumbnail.thumbnail_package_service import ThumbnailPackageService
from src.services.title_card_text_resolution_service import resolve_title_card_text

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

# REQ-4 (opening title card): "" represents the real default (None on
# VideoJob.title_card_text_position, which resolves to CENTER) rather
# than an explicit CENTER override - keeping the distinction visible
# in the UI (an unset override vs. an explicit choice that happens to
# also be CENTER) even though both currently render identically.
_TITLE_CARD_POSITION_LABELS: list[tuple[str, str]] = [
    ("Auto (center)", ""),
    ("Top", ThumbnailTextPosition.TOP.value),
    ("Bottom", ThumbnailTextPosition.BOTTOM.value),
    ("Center left", ThumbnailTextPosition.CENTER_LEFT.value),
    ("Center right", ThumbnailTextPosition.CENTER_RIGHT.value),
]


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


def _render_size(job: VideoJob) -> tuple[int, int]:
    """The (width, height) the project renders at, e.g. "1080x1920" -> (1080, 1920)."""

    try:
        width_text, height_text = job.output_resolution.lower().split("x")
        width, height = int(width_text), int(height_text)
    except ValueError:
        return 1920, 1080

    return (width, height) if width > 0 and height > 0 else (1920, 1080)


def _audience_fallback(job: VideoJob) -> str | None:
    """The audience to hand the SEO builder when the project has no audience promise.

    None keeps the project's own audience. Otherwise the same neutral default the
    SEO and thumbnail cards pre-fill, so the title card and export variants do not
    fail where those cards work (live, 2026-10-07)."""

    return None if job.audience_promise is not None else "General audience"


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


class _ExportVariantWorker(QObject):
    """
    Runs one export-variant FFmpeg pass off the Qt main thread.

    Mirrors RenderWorkspaceView's own _RenderWorker exactly, including
    the real reason for its specific shape: AutoConnection only
    detects that a Qt signal needs queued, main-thread delivery when
    the receiving slot is a bound method of a real QObject (it reads
    the method's __self__ to find the owning thread) - a lambda slot
    has no such owner, so the handler would silently run directly on
    this worker's own background thread instead, mutating GUI widgets
    from off the main thread (undefined behaviour in Qt - the exact
    cause of a real, intermittent heap-corruption crash, 0xc0000374,
    documented on _RenderWorker). job_id, render_result, orientation,
    and platform therefore all travel as plain attributes (read back
    via self.sender() in each handler, e.g. to retry after a failure),
    never via a lambda closure, so every connection below can target a
    real bound method.
    """

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        service: ExportVariantRenderService,
        job: VideoJob,
        render_result: RenderResult,
        orientation: AspectRatio,
        platform: Platform | None,
    ) -> None:
        super().__init__()

        self._service = service
        self._job = job
        self.job_id = job.id
        self.render_result = render_result
        self.orientation = orientation
        self.platform = platform
        self._cancel_event = threading.Event()

    def run(self) -> None:
        try:
            variant = self._service.build(
                job=self._job,
                render_result=self.render_result,
                orientation=self.orientation,
                platform=self.platform,
                progress_callback=self.progress.emit,
                cancellation_check=self._cancel_event.is_set,
            )
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit(variant)

    def request_cancel(self) -> None:
        self._cancel_event.set()


class _SubtitleBurnWorker(QObject):
    """Burns the subtitles onto a copy of one finished video off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        service: SubtitleBurnActionService,
        job: VideoJob,
        job_id: UUID,
        source_file: str,
        output_file: str,
        after_title_card_file: str | None,
    ) -> None:
        super().__init__()

        self._service = service
        self._job = job
        self._source_file = source_file
        self._output_file = output_file
        # When set, the subtitles are shifted past the opening title card that the render
        # at this path starts with (an export variant starts with the same card).
        self._after_title_card_file = after_title_card_file
        self.job_id = job_id
        self._cancel_event = threading.Event()

    def run(self) -> None:
        try:
            offset = (
                self._service.offset_seconds(self._job, self._after_title_card_file)
                if self._after_title_card_file
                else 0.0
            )
            result = self._service.burn(
                job=self._job,
                source_file=self._source_file,
                output_file=self._output_file,
                offset_seconds=offset,
                cancellation_check=self._cancel_event.is_set,
            )
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit(result)

    def request_cancel(self) -> None:
        self._cancel_event.set()


class _TitleCardWorker(QObject):
    """Same real pattern/crash-avoidance reasoning as _ExportVariantWorker above."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        service: OpeningTitleCardService,
        job_id: UUID,
        render_orchestration_result: RenderOrchestrationResult,
        seo_context: SEOContext | None,
        genre_id: str,
        channel_name: str,
        topic: str,
        main_video_file: str,
        main_video_duration_seconds: float,
        output_file: str,
        selected_seo_title: str | None,
        image_override: str | None,
        title_override: str | None = None,
        position_override: ThumbnailTextPosition | None = None,
        title_clip_override: str | None = None,
        width: int = 1920,
        height: int = 1080,
    ) -> None:
        super().__init__()

        self._service = service
        self._width = width
        self._height = height
        self._seo_context = seo_context
        self._genre_id = genre_id
        self._channel_name = channel_name
        self._topic = topic
        self._main_video_file = main_video_file
        self._main_video_duration_seconds = main_video_duration_seconds
        self._output_file = output_file
        self._selected_seo_title = selected_seo_title
        self._image_override = image_override
        self._title_override = title_override
        self._position_override = position_override
        self._title_clip_override = title_clip_override
        self.job_id = job_id
        # Carried as a plain attribute (not re-derived at finish time)
        # so the finished handler can model_copy() it with the new
        # render_result exactly as the previous synchronous handler
        # did - re-resolving it fresh at finish time could race a
        # concurrent change to job_store's own cache.
        self.render_orchestration_result = render_orchestration_result
        self._cancel_event = threading.Event()

    def run(self) -> None:
        try:
            result = self._service.build(
                seo_context=self._seo_context,
                genre_id=self._genre_id,
                channel_name=self._channel_name,
                topic=self._topic,
                main_video_file=self._main_video_file,
                main_video_duration_seconds=self._main_video_duration_seconds,
                output_file=self._output_file,
                selected_seo_title=self._selected_seo_title,
                image_override=self._image_override,
                title_override=self._title_override,
                position_override=self._position_override,
                title_clip_override=self._title_clip_override,
                width=self._width,
                height=self._height,
                progress_callback=self.progress.emit,
                cancellation_check=self._cancel_event.is_set,
            )
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit(result)

    def request_cancel(self) -> None:
        self._cancel_event.set()


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
        subtitle_burn_action_service: SubtitleBurnActionService | None = None,
        opening_title_card_service: OpeningTitleCardService | None = None,
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
        # REQ-4 (opening title card): unlike export_variant_render_
        # service above, this cannot default-construct on its own - it
        # needs real, already-configured image/music generation
        # services (see services.get_opening_title_card_service()).
        # None means "not wired up by this caller" - the title card
        # card shows a real, disclosed message instead of a button
        # rather than crashing.
        self._opening_title_card_service = opening_title_card_service
        self._job_id: UUID | None = None

        # Real-world finding, 2026-10-01: both export-variant and
        # title-card generation are real, potentially multi-minute
        # FFmpeg passes over the full video - running them straight on
        # the GUI thread (this view's own prior pattern, matching every
        # other synchronous action here) froze the whole app, reported
        # by Windows as "Not Responding", blocking every other action
        # for the whole duration. Threading/bookkeeping below mirrors
        # RenderWorkspaceView's own _render_threads/_rendering_job_ids
        # pattern exactly (see _ExportVariantWorker's own docstring for
        # why the bound-method, not-lambda signal wiring matters).
        self._export_variant_threads: dict[
            UUID, tuple[QThread, _ExportVariantWorker]
        ] = {}
        self._generating_export_variant_job_ids: set[UUID] = set()
        self._title_card_threads: dict[UUID, tuple[QThread, _TitleCardWorker]] = {}
        self._generating_title_card_job_ids: set[UUID] = set()
        # Burning subtitles onto a finished video (any of the renders).
        self._subtitle_burn_action_service = (
            subtitle_burn_action_service or SubtitleBurnActionService()
        )
        self._subtitle_threads: dict[UUID, tuple[QThread, _SubtitleBurnWorker]] = {}
        self._burning_subtitle_job_ids: set[UUID] = set()
        # What the last burn did, shown under the button: (role, text).
        self._subtitle_notices: dict[UUID, tuple[str, str]] = {}
        # Which section's button started the last burn, so its result shows there.
        self._subtitle_notice_section: dict[UUID, str] = {}
        # One picker per place the burn button appears: (picker, the videos it offers).
        self._subtitle_sections: dict[
            str, tuple[QComboBox, list[SubtitleBurnTarget]]
        ] = {}

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

        # Every action rebuilds this tab's cards; without this each one threw the
        # operator back to the top (see src/desktop/scroll_preservation.py).
        keep_scroll_on_refresh(self, scroll_area)

    def set_job(self, job_id: UUID) -> None:
        self._job_id = job_id

    def refresh(self, job: VideoJob) -> None:
        if (
            job.id in self._generating_export_variant_job_ids
            or job.id in self._generating_title_card_job_ids
            or job.id in self._burning_subtitle_job_ids
        ):
            # A generation is in flight for this job - its progress
            # widgets are being updated live by the signal handlers
            # below, not through refresh(). refresh() can be triggered
            # by an unrelated workspace's own on_change (every
            # workspace shares the same on_change callback), so
            # rebuilding here would destroy the live widgets mid-
            # generation even though this workspace isn't the one that
            # changed - same real guard RenderWorkspaceView's own
            # refresh() already needed for its main render.
            return

        self._rebuild_all(job)

    def _rebuild_all(self, job: VideoJob) -> None:
        self._subtitle_sections = {}

        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_seo_card(job)
        self._build_title_card_card(job)
        self._build_thumbnail_card(job)
        self._build_export_variants_card(job)
        self._build_subtitle_burn_card(job)
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

    def _build_title_card_card(self, job: VideoJob) -> None:
        """
        REQ-4 (opening title card): real per-project opt-in control -
        default OFF (this spends real, billed generation cost every
        enabled render, so genre never decides this, only the user
        does), plus a manual title-text override (pre-filled with
        what would auto-resolve: SEOPackage.selected_title, falling
        back to topic) and a 5-way position override. Same screen the
        CTA/export-variant controls and the real SEO title already
        live on, per the user's own explicit design choice - this
        override sits right next to the SEO title it defaults from.
        """

        frame, layout = card("Opening title card", icon_name="clapper")

        layout.addWidget(
            small_muted(
                "A short branded intro before the video starts - a "
                "dedicated AI-generated image and music sting, every "
                "time it's enabled. Real generation cost, so it's off "
                "by default."
            )
        )

        assert self._job_id is not None

        enabled_checkbox = QCheckBox("Add an opening title card to this render")
        enabled_checkbox.setChecked(job.title_card_enabled)
        layout.addWidget(enabled_checkbox)

        seo_package = self._job_store.get_seo_package(self._job_id)

        auto_resolved_title = resolve_title_card_text(
            override=None,
            selected_seo_title=(
                seo_package.selected_title if seo_package is not None else None
            ),
            topic=job.topic,
        )

        form = QFormLayout()
        form.setSpacing(8)

        title_input = QLineEdit(job.title_card_text or "")
        title_input.setPlaceholderText(f"Auto: {auto_resolved_title}")
        form.addRow("Title text (optional override)", title_input)

        position_select = QComboBox()
        position_select.addItems([label for label, _ in _TITLE_CARD_POSITION_LABELS])

        current_position_value = (
            job.title_card_text_position.value
            if job.title_card_text_position is not None
            else ""
        )

        for index, (_label, value) in enumerate(_TITLE_CARD_POSITION_LABELS):
            if value == current_position_value:
                position_select.setCurrentIndex(index)
                break

        form.addRow("Text position", position_select)

        layout.addLayout(form)

        # REQ-12-adjacent, 2026-09-23: same real "manual override wins
        # over AI generation" option added for the top10 countdown's
        # own background image, applied here too. Auto/Manual is
        # deliberately not a separate persisted mode flag - the image
        # path itself IS the mode: empty means auto-generate, a real
        # path means use it directly. "Auto-generate image" simply
        # clears the field; "Upload my own image..." opens a picker
        # and only changes the field if a file is actually chosen
        # (cancelling the dialog leaves whatever was there before).
        layout.addWidget(subheading("Title card source"))

        image_path_display = QLineEdit(job.title_card_image_path or "")
        image_path_display.setReadOnly(True)
        image_path_display.setPlaceholderText(
            "Auto-generate a dedicated AI image (default)"
        )

        clip_path_display = QLineEdit(job.title_card_clip_path or "")
        clip_path_display.setReadOnly(True)
        clip_path_display.setPlaceholderText("No clip - a title card is generated")

        clip_note = small_muted(
            "Your clip is used as the title card - it is added to the front "
            "of the render as-is, so the title text and position above are "
            "not used."
        )

        def apply_source_mode() -> None:
            # A clip already contains its own text, so the generated
            # card's title/position fields mean nothing for it.
            using_clip = bool(clip_path_display.text().strip())
            title_input.setEnabled(not using_clip)
            position_select.setEnabled(not using_clip)
            clip_note.setVisible(using_clip)

        def choose_image() -> None:
            self._handle_browse_title_card_image(image_path_display)

            # One source at a time: picking an image drops any clip.
            if image_path_display.text().strip() != (job.title_card_image_path or ""):
                clip_path_display.clear()

        def choose_clip() -> None:
            self._handle_browse_cta_file(
                clip_path_display,
                "Select a title clip",
                "Video files (*.mp4 *.mov *.mkv *.webm *.m4v)",
            )

            if clip_path_display.text().strip() != (job.title_card_clip_path or ""):
                image_path_display.clear()

        def choose_auto() -> None:
            image_path_display.clear()
            clip_path_display.clear()

        auto_image_button = button("Auto-generate image")
        auto_image_button.clicked.connect(choose_auto)

        upload_image_button = button("Upload my own image...")
        upload_image_button.clicked.connect(choose_image)

        upload_clip_button = button("Upload my own clip...")
        upload_clip_button.clicked.connect(choose_clip)

        layout.addLayout(
            row(auto_image_button, upload_image_button, upload_clip_button)
        )
        layout.addWidget(image_path_display)
        layout.addWidget(clip_path_display)
        layout.addWidget(clip_note)

        clip_path_display.textChanged.connect(lambda _text: apply_source_mode())
        apply_source_mode()

        save_button = button("Save title card settings", icon_name="check")
        save_button.clicked.connect(
            lambda: self._handle_save_title_card_settings(
                enabled_checkbox=enabled_checkbox,
                title_input=title_input,
                position_select=position_select,
                image_path_display=image_path_display,
                clip_path_display=clip_path_display,
            )
        )
        layout.addWidget(save_button, alignment=_LEFT)

        if job.title_card_enabled:
            layout.addWidget(subheading("Apply to your render"))

            if self._opening_title_card_service is None:
                layout.addWidget(
                    small_muted("Title card generation is not configured.")
                )
            else:
                assert self._job_id is not None

                render_orchestration_result = (
                    resolve_effective_render_orchestration_result(
                        job, self._job_store.get_render_result(self._job_id)
                    )
                )
                render_result = (
                    render_orchestration_result.render_result
                    if render_orchestration_result is not None
                    else None
                )

                if (
                    render_orchestration_result is None
                    or not render_orchestration_result.success
                    or render_result is None
                    or render_result.output_file is None
                ):
                    layout.addWidget(
                        small_muted(
                            "Requires a successful render (see Render "
                            "Workspace) before a title card can be applied."
                        )
                    )
                elif not (job.title_card_image_path or job.title_card_clip_path):
                    # Real-world finding, 2026-09-30: no real AI image-
                    # generation provider is wired into this app yet for
                    # ANY image path - "Auto-generate image" (the
                    # default when no upload is set) always fell
                    # through to DryRunThumbnailImageProvider, whose
                    # placeholder "dry-run://..." string FFmpeg cannot
                    # open ("Protocol not found"), crashing every
                    # attempt. Hidden here rather than left to crash -
                    # uploading a real background image (now correctly
                    # used, see image_override below) is the only
                    # working path until a real provider exists.
                    layout.addWidget(
                        small_muted(
                            "Auto-generated background images aren't "
                            "available yet (no AI image provider is "
                            "configured) - upload your own background "
                            "image above to enable title card generation."
                        )
                    )
                elif job.id in self._generating_title_card_job_ids:
                    self._build_title_card_progress_state(layout)
                else:
                    generate_title_card_button = button(
                        (
                            "Add my clip to the render"
                            if job.title_card_clip_path
                            else "Generate title card onto the render"
                        ),
                        variant="primary",
                        icon_name="clapper",
                    )
                    generate_title_card_button.clicked.connect(
                        self._handle_generate_title_card
                    )
                    layout.addWidget(generate_title_card_button, alignment=_LEFT)

        if job.title_card_enabled:
            layout.addWidget(subheading("Subtitles"))
            self._build_subtitle_burn_controls(
                layout,
                job,
                section="title_card",
                kinds={"title_card"},
                button_text="Burn subtitles onto the render with the title card",
                empty_hint=(
                    "Add the title card to the render first - then subtitles can be "
                    "burned onto it here."
                ),
            )

        self._layout.addWidget(frame)

    def _build_title_card_progress_state(self, layout: QVBoxLayout) -> None:
        layout.addWidget(subheading("Generating title card..."))

        self._title_card_progress_bar = QProgressBar()
        self._title_card_progress_bar.setRange(0, 100)
        self._title_card_progress_bar.setValue(0)
        layout.addWidget(self._title_card_progress_bar)

        self._title_card_progress_time_label = small_muted("0.0s")
        layout.addWidget(self._title_card_progress_time_label)

        self._title_card_progress_speed_label = small_muted("Speed: —")
        layout.addWidget(self._title_card_progress_speed_label)

        stop_button = button("Stop", variant="danger")
        stop_button.clicked.connect(self._handle_stop_title_card_generation)
        layout.addWidget(stop_button, alignment=_LEFT)

    def _handle_generate_title_card(self) -> None:
        """
        REQ-4 (opening title card) real trigger: takes the job's
        already-rendered video and prepends a real title card onto it,
        replacing job_store's own render result with the new, longer
        final file - the same file REQ-0A's own download/review
        actions and this card's own export-variant pass already read
        from, so no separate "which file is the real one" concept is
        introduced.

        Real-world finding, 2026-10-01: this used to run synchronously
        on the GUI thread - a real, potentially multi-minute FFmpeg
        pass, reported by Windows as "Not Responding" for its whole
        duration and blocking every other action in the app. Now runs
        on a background QThread (see _TitleCardWorker), matching
        RenderWorkspaceView's own established pattern for its main
        render.
        """

        job = self._current_job()

        if (
            job is None
            or self._job_id is None
            or self._opening_title_card_service is None
            # No real AI image-generation provider exists yet - see
            # this view's own "Apply to your render" gate for the full
            # real-world finding. Guarded here too (not just at the
            # button's own visibility) so this handler is never called
            # in a state that would crash FFmpeg on a fake
            # "dry-run://..." path.
            or not (job.title_card_image_path or job.title_card_clip_path)
        ):
            return

        if job.id in self._generating_title_card_job_ids:
            # Already generating for this job - the UI already
            # reflects this (button replaced by progress state), this
            # is just defense in depth.
            return

        render_orchestration_result = resolve_effective_render_orchestration_result(
            job, self._job_store.get_render_result(self._job_id)
        )

        if render_orchestration_result is None:
            return

        render_result = render_orchestration_result.render_result

        if render_result is None or render_result.output_file is None:
            return

        # Real-world finding, 2026-10-03: a successful apply replaces the
        # stored render result with the with-title-card file, so applying
        # again (e.g. after fixing the title) used THAT file as its
        # input and stacked a second card on the first. VideoJob.
        # render_result is never touched by title card generation, so it
        # is always the original, card-free render - build from it.
        if (
            job.render_result is not None
            and job.render_result.success
            and job.render_result.output_file is not None
        ):
            render_result = job.render_result

        assert render_result.output_file is not None

        seo_package = self._job_store.get_seo_package(self._job_id)
        render_width, render_height = _render_size(job)

        main_video_path = Path(render_result.output_file)

        output_file = str(
            main_video_path.with_name(
                f"{main_video_path.stem}_with_title_card{main_video_path.suffix}"
            )
        )

        # The SEO context only feeds the AI-generated card background: the
        # operator's own clip or image never needs it (live, 2026-10-07: a
        # project without research could not use its own title clip).
        context: SEOContext | None = None

        if not (job.title_card_clip_path or job.title_card_image_path):
            try:
                context = SEOContextBuilder().build(
                    job,
                    genre_id=_resolved_genre_id(job),
                    target_audience=_audience_fallback(job),
                )
            except (RuntimeError, ValueError) as error:
                self._record_error(
                    job,
                    f"Title card generation failed: {error}",
                    on_retry=self._handle_generate_title_card,
                )

                return

        thread = QThread()
        worker = _TitleCardWorker(
            service=self._opening_title_card_service,
            job_id=job.id,
            render_orchestration_result=render_orchestration_result,
            seo_context=context,
            genre_id=_resolved_genre_id(job),
            channel_name=job.channel_name,
            topic=job.topic,
            main_video_file=render_result.output_file,
            main_video_duration_seconds=float(render_result.duration_seconds),
            output_file=output_file,
            selected_seo_title=(
                seo_package.selected_title if seo_package is not None else None
            ),
            # Real-world finding, 2026-09-30: this call never read
            # job.title_card_image_path (what "Save title card
            # settings" actually persists when the operator uploads
            # their own image) - it always fell through to
            # OpeningTitleCardService.build()'s own auto-generate
            # path instead, silently ignoring a real upload.
            image_override=job.title_card_image_path,
            # Real-world finding, 2026-10-02: the title text and
            # position saved under "Save title card settings" were
            # never passed here either, so the card always showed the
            # auto-resolved SEO title/topic no matter what the
            # operator typed. None still means "auto".
            title_override=job.title_card_text,
            position_override=job.title_card_text_position,
            title_clip_override=job.title_card_clip_path,
            # A 9:16 project's generated title card is made at the render's own size.
            width=render_width,
            height=render_height,
        )
        worker.moveToThread(thread)

        job_id = job.id
        # QThread is a QObject too, so it can carry the same job_id
        # attribute the worker does - thread.finished (connected
        # below) has no signal argument to carry it as a parameter
        # instead.
        thread.job_id = job_id  # type: ignore[attr-defined]

        thread.started.connect(worker.run)
        worker.progress.connect(self._handle_title_card_progress)
        worker.finished.connect(self._handle_title_card_finished)
        worker.failed.connect(self._handle_title_card_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._handle_title_card_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._title_card_threads[job_id] = (thread, worker)
        self._generating_title_card_job_ids.add(job_id)

        # Show the in-progress state immediately - nothing else
        # refreshes this workspace until generation finishes (see
        # refresh()'s own guard above).
        self._rebuild_all(job)

        thread.start()

    def _handle_title_card_progress(self, progress: RenderProgress) -> None:
        worker = self.sender()
        job_id = worker.job_id if isinstance(worker, _TitleCardWorker) else None

        if job_id is None or job_id != self._job_id:
            return

        self._title_card_progress_bar.setValue(int(progress.progress_percent))

        if progress.total_duration_seconds is not None:
            self._title_card_progress_time_label.setText(
                f"{progress.processed_duration_seconds:.1f}s / "
                f"{progress.total_duration_seconds:.1f}s"
            )
        else:
            self._title_card_progress_time_label.setText(
                f"{progress.processed_duration_seconds:.1f}s"
            )

        self._title_card_progress_speed_label.setText(
            f"Speed: {progress.speed:.2f}x"
            if progress.speed is not None
            else "Speed: —"
        )

    def _handle_title_card_finished(self, result: RenderResult) -> None:
        worker = self.sender()

        if not isinstance(worker, _TitleCardWorker):
            return

        job_id = worker.job_id
        self._generating_title_card_job_ids.discard(job_id)

        job = self._job_store.get(job_id)

        if not result.success:
            message = result.error_message or "Title card generation failed."

            if job is not None and job_id == self._job_id:
                self._record_error(
                    job, message, on_retry=self._handle_generate_title_card
                )
            elif job is not None:
                job.errors.append(f"Title card generation failed: {message}")

            return

        self._job_store.set_render_result(
            job_id,
            replace_orchestration_render_result(
                worker.render_orchestration_result, result
            ),
        )

        if job_id == self._job_id:
            self._on_change()

    def _handle_title_card_failed(self, message: str) -> None:
        worker = self.sender()

        if not isinstance(worker, _TitleCardWorker):
            return

        job_id = worker.job_id
        self._generating_title_card_job_ids.discard(job_id)

        job = self._job_store.get(job_id)

        if job is None:
            return

        if job_id == self._job_id:
            self._record_error(
                job,
                f"Title card generation failed: {message}",
                on_retry=self._handle_generate_title_card,
            )
        else:
            job.errors.append(f"Title card generation failed: {message}")

    def _handle_title_card_thread_finished(self) -> None:
        """
        Drop the (thread, worker) bookkeeping entry once the QThread
        has actually stopped.

        Bound-method connection for the same cross-thread-safety
        reason as the worker signals above - self.sender() here is
        the QThread instance itself, which carries job_id as a plain
        attribute (set above) since this signal has no arguments to
        carry it as a parameter.
        """

        thread = self.sender()
        job_id = getattr(thread, "job_id", None)

        if job_id is not None:
            self._title_card_threads.pop(job_id, None)

    def _handle_stop_title_card_generation(self) -> None:
        if self._job_id is None:
            return

        entry = self._title_card_threads.get(self._job_id)

        if entry is None:
            return

        _thread, worker = entry
        worker.request_cancel()

    def _handle_browse_title_card_image(self, image_path_display: QLineEdit) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select a background image for the title card",
            "",
            "Image files (*.png *.jpg *.jpeg *.webp)",
        )

        if file_path:
            image_path_display.setText(file_path)

    def _handle_save_title_card_settings(
        self,
        *,
        enabled_checkbox: QCheckBox,
        title_input: QLineEdit,
        position_select: QComboBox,
        image_path_display: QLineEdit,
        clip_path_display: QLineEdit,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        job.title_card_enabled = enabled_checkbox.isChecked()

        title_text = title_input.text().strip()

        job.title_card_text = title_text or None

        selected_label = position_select.currentText()

        selected_value = next(
            (
                value
                for label, value in _TITLE_CARD_POSITION_LABELS
                if label == selected_label
            ),
            "",
        )

        job.title_card_text_position = (
            ThumbnailTextPosition(selected_value) if selected_value else None
        )

        image_path = image_path_display.text().strip()

        clip_path = clip_path_display.text().strip()

        # One source at a time: a clip replaces the generated card, so
        # a stale image path must not linger beside it.
        job.title_card_clip_path = clip_path or None
        job.title_card_image_path = None if clip_path else (image_path or None)

        self._on_change()

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

    # ----------------------------------------------------------- subtitles

    def _effective_render(self, job: VideoJob) -> RenderResult | None:
        assert self._job_id is not None

        orchestration = resolve_effective_render_orchestration_result(
            job, self._job_store.get_render_result(self._job_id)
        )

        return orchestration.render_result if orchestration is not None else None

    def _build_subtitle_burn_card(self, job: VideoJob) -> None:
        """
        Burn the project's subtitles onto a finished video at any stage - the main render,
        the render with its title card, or an export variant. A copy is made; the original
        stays as it is. (Subtitles used to be burned in only inside the main render.)
        The title card and export variants sections carry the same button for their own
        video, so it is where the operator is already working.
        """

        frame, layout = card("Subtitles", icon_name="clapper")

        layout.addWidget(
            small_muted(
                "Burn this project's subtitles onto any finished video. A copy named "
                "..._subtitled is made next to it; the original is not changed."
            )
        )
        self._build_subtitle_burn_controls(
            layout,
            job,
            section="all",
            kinds=None,
            button_text="Burn subtitles onto this video",
            empty_hint="There is no finished video file to use.",
        )
        self._layout.addWidget(frame)

    def _build_subtitle_burn_controls(
        self,
        layout: QVBoxLayout,
        job: VideoJob,
        *,
        section: str,
        kinds: set[str] | None,
        button_text: str,
        empty_hint: str,
    ) -> None:
        """The picker and button that burn subtitles onto a copy of a finished video.
        `kinds` limits which videos are offered (None = all three)."""

        assert self._job_id is not None

        reason = SubtitleBurnActionService.unavailable_reason(job)

        if reason is not None:
            layout.addWidget(small_muted(reason))

            return

        if job.id in self._burning_subtitle_job_ids:
            layout.addWidget(subheading("Burning subtitles..."))
            layout.addWidget(small_muted("This takes about as long as a short render."))

            return

        assert job.render_result is not None

        if job.render_result.subtitles_burned:
            layout.addWidget(
                small_muted(
                    "The main render already has subtitles burned in, and so does "
                    "everything made from it."
                )
            )

            return

        targets = [
            target
            for target in subtitle_burn_targets(
                job,
                self._effective_render(job),
                self._job_store.get_export_variants(self._job_id),
            )
            if kinds is None or target.kind in kinds
        ]

        if not targets:
            layout.addWidget(small_muted(empty_hint))

            return

        combo = QComboBox()

        for target in targets:
            combo.addItem(target.label, userData=target.file)

        self._subtitle_sections[section] = (combo, targets)

        if len(targets) > 1 or kinds is None:
            layout.addWidget(combo)

        burn_button = button(button_text, variant="primary")
        burn_button.clicked.connect(
            lambda _checked=False, name=section: self._handle_burn_subtitles(name)
        )
        layout.addWidget(burn_button, alignment=_LEFT)

        notice = self._subtitle_notices.get(job.id)

        if notice is not None and self._subtitle_notice_section.get(job.id) == section:
            role, text = notice
            layout.addWidget(status_label(text, role=role))

    def _handle_burn_subtitles(self, section: str = "all") -> None:
        job = self._current_job()
        picked = self._subtitle_sections.get(section)

        if (
            job is None
            or self._job_id is None
            or job.id in self._burning_subtitle_job_ids
            or picked is None
        ):
            return

        combo, targets = picked
        index = combo.currentIndex()

        if not 0 <= index < len(targets):
            return

        target = targets[index]
        effective = self._effective_render(job)
        service = self._subtitle_burn_action_service

        thread = QThread()
        worker = _SubtitleBurnWorker(
            service=service,
            job=job.model_copy(deep=True),
            job_id=job.id,
            source_file=target.file,
            output_file=service.output_file_for(target.file),
            after_title_card_file=(
                effective.output_file
                if target.after_title_card
                and effective is not None
                and effective.output_file
                else None
            ),
        )
        worker.moveToThread(thread)
        thread.job_id = job.id  # type: ignore[attr-defined]

        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_subtitle_burn_finished)
        worker.failed.connect(self._handle_subtitle_burn_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._handle_subtitle_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._subtitle_threads[job.id] = (thread, worker)
        self._burning_subtitle_job_ids.add(job.id)
        self._subtitle_notices.pop(job.id, None)
        self._subtitle_notice_section[job.id] = section
        self._rebuild_all(job)

        thread.start()

    def _handle_subtitle_burn_finished(self, result: RenderResult) -> None:
        worker = self.sender()

        if not isinstance(worker, _SubtitleBurnWorker):
            return

        job_id = worker.job_id
        self._burning_subtitle_job_ids.discard(job_id)

        if result.success and result.output_file:
            self._subtitle_notices[job_id] = (
                "success",
                f"Subtitles burned into a copy: {result.output_file}",
            )
        else:
            self._subtitle_notices[job_id] = (
                "error",
                result.error_message or "Burning the subtitles failed.",
            )

        job = self._job_store.get(job_id)

        if job is not None and job_id == self._job_id:
            self._rebuild_all(job)

    def _handle_subtitle_burn_failed(self, message: str) -> None:
        worker = self.sender()

        if not isinstance(worker, _SubtitleBurnWorker):
            return

        job_id = worker.job_id
        self._burning_subtitle_job_ids.discard(job_id)
        self._subtitle_notices[job_id] = (
            "error",
            f"Subtitles were not burned: {message}",
        )
        job = self._job_store.get(job_id)

        if job is not None and job_id == self._job_id:
            self._rebuild_all(job)

    def _handle_subtitle_thread_finished(self) -> None:
        thread = self.sender()
        job_id = getattr(thread, "job_id", None)

        if job_id is not None:
            self._subtitle_threads.pop(job_id, None)

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

        render_orchestration_result = resolve_effective_render_orchestration_result(
            job, self._job_store.get_render_result(self._job_id)
        )
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

        if job.id in self._generating_export_variant_job_ids:
            self._build_export_variant_progress_state(layout)
        else:
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
            self._build_cta_upload_controls(layout, job)
            layout.addWidget(generate_button, alignment=_LEFT)

        layout.addWidget(subheading("Subtitles"))
        self._build_subtitle_burn_controls(
            layout,
            job,
            section="variants",
            kinds={"variant"},
            button_text="Burn subtitles onto this variant",
            empty_hint=(
                "Generate a variant first - then subtitles can be burned onto it here."
            ),
        )

        self._layout.addWidget(frame)

    def _build_cta_upload_controls(self, layout: QVBoxLayout, job: VideoJob) -> None:
        """
        Optional operator-supplied branding for platform variants: an
        image used as the watermark, and a short clip appended as the
        end CTA. Leaving either empty keeps the generated default
        (text watermark / 5s text end-card). Saved explicitly, like the
        title card settings, and applied when a variant is generated -
        so a different look per platform is just "swap, save, generate".
        """

        layout.addWidget(subheading("Watermark and CTA (optional)"))
        layout.addWidget(
            small_muted(
                "Used when a platform is selected. Leave a field empty to "
                "keep the generated default."
            )
        )

        layout.addWidget(small_muted("Watermark image (shown over the video)"))
        watermark_display = QLineEdit(job.cta_watermark_image_path or "")
        watermark_display.setReadOnly(True)
        watermark_display.setPlaceholderText("Default: generated text watermark")
        upload_watermark_button = button("Upload my own image...")
        upload_watermark_button.clicked.connect(
            lambda: self._handle_browse_cta_file(
                watermark_display,
                "Select a watermark image",
                "Image files (*.png *.jpg *.jpeg *.webp)",
            )
        )
        remove_watermark_button = button("Remove")
        remove_watermark_button.clicked.connect(watermark_display.clear)
        layout.addLayout(row(upload_watermark_button, remove_watermark_button))
        layout.addWidget(watermark_display)

        layout.addWidget(small_muted("CTA clip (added at the end)"))
        clip_display = QLineEdit(job.cta_end_clip_path or "")
        clip_display.setReadOnly(True)
        clip_display.setPlaceholderText("Default: generated 5s text end-card")
        upload_clip_button = button("Upload my own clip...")
        upload_clip_button.clicked.connect(
            lambda: self._handle_browse_cta_file(
                clip_display,
                "Select a CTA clip",
                "Video files (*.mp4 *.mov *.mkv *.webm *.m4v)",
            )
        )
        remove_clip_button = button("Remove")
        remove_clip_button.clicked.connect(clip_display.clear)
        layout.addLayout(row(upload_clip_button, remove_clip_button))
        layout.addWidget(clip_display)

        save_button = button("Save CTA settings", icon_name="check")
        save_button.clicked.connect(
            lambda: self._handle_save_cta_settings(
                watermark_display=watermark_display,
                clip_display=clip_display,
            )
        )
        layout.addWidget(save_button, alignment=_LEFT)

    def _handle_browse_cta_file(
        self, display: QLineEdit, title: str, file_filter: str
    ) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self, title, "", file_filter
        )

        # Cancelling the dialog leaves whatever was there before.
        if file_path:
            display.setText(file_path)

    def _handle_save_cta_settings(
        self, *, watermark_display: QLineEdit, clip_display: QLineEdit
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        job.cta_watermark_image_path = watermark_display.text().strip() or None
        job.cta_end_clip_path = clip_display.text().strip() or None

        self._on_change()

    def _build_export_variant_progress_state(self, layout: QVBoxLayout) -> None:
        layout.addWidget(subheading("Generating export variant..."))

        self._export_variant_progress_bar = QProgressBar()
        self._export_variant_progress_bar.setRange(0, 100)
        self._export_variant_progress_bar.setValue(0)
        layout.addWidget(self._export_variant_progress_bar)

        self._export_variant_progress_time_label = small_muted("0.0s")
        layout.addWidget(self._export_variant_progress_time_label)

        self._export_variant_progress_speed_label = small_muted("Speed: —")
        layout.addWidget(self._export_variant_progress_speed_label)

        stop_button = button("Stop", variant="danger")
        stop_button.clicked.connect(self._handle_stop_export_variant_generation)
        layout.addWidget(stop_button, alignment=_LEFT)

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
        render_result = resolve_effective_render_orchestration_result(
            job, self._job_store.get_render_result(self._job_id)
        )
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

        render_result = resolve_effective_render_result(
            job, self._job_store.get_render_result(self._job_id)
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
        # _ORIENTATION_LABELS); converted back here. Read as PLAIN
        # values, not kept as widget references - once generation
        # starts, this card rebuilds into the progress state and these
        # combo widgets get destroyed (see _rebuild_all).
        orientation_value = orientation_combo.currentData()

        if not isinstance(orientation_value, str):
            return

        try:
            orientation = AspectRatio(orientation_value)
        except ValueError:
            return

        platform = self._read_platform(platform_combo)

        self._execute_export_variant_generation(
            job,
            render_result=render_result,
            orientation=orientation,
            platform=platform,
        )

    def _execute_export_variant_generation(
        self,
        job: VideoJob,
        *,
        render_result: RenderResult,
        orientation: AspectRatio,
        platform: Platform | None,
    ) -> None:
        """
        Real-world finding, 2026-10-01: this used to run synchronously
        on the GUI thread - a real, potentially multi-minute FFmpeg
        pass over the full video, reported by Windows as "Not
        Responding" for its whole duration and blocking every other
        action in the app. Now runs on a background QThread (see
        _ExportVariantWorker), matching RenderWorkspaceView's own
        established pattern for its main render.
        """

        if self._job_id is None or job.id in self._generating_export_variant_job_ids:
            # Already generating for this job - the UI already
            # reflects this (controls replaced by progress state), this
            # is just defense in depth.
            return

        thread = QThread()
        worker = _ExportVariantWorker(
            service=self._export_variant_render_service,
            job=job,
            render_result=render_result,
            orientation=orientation,
            platform=platform,
        )
        worker.moveToThread(thread)

        job_id = job.id
        thread.job_id = job_id  # type: ignore[attr-defined]

        thread.started.connect(worker.run)
        worker.progress.connect(self._handle_export_variant_progress)
        worker.finished.connect(self._handle_export_variant_finished)
        worker.failed.connect(self._handle_export_variant_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._handle_export_variant_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._export_variant_threads[job_id] = (thread, worker)
        self._generating_export_variant_job_ids.add(job_id)

        self._rebuild_all(job)

        thread.start()

    def _handle_export_variant_progress(self, progress: RenderProgress) -> None:
        worker = self.sender()
        job_id = worker.job_id if isinstance(worker, _ExportVariantWorker) else None

        if job_id is None or job_id != self._job_id:
            return

        self._export_variant_progress_bar.setValue(int(progress.progress_percent))

        if progress.total_duration_seconds is not None:
            self._export_variant_progress_time_label.setText(
                f"{progress.processed_duration_seconds:.1f}s / "
                f"{progress.total_duration_seconds:.1f}s"
            )
        else:
            self._export_variant_progress_time_label.setText(
                f"{progress.processed_duration_seconds:.1f}s"
            )

        self._export_variant_progress_speed_label.setText(
            f"Speed: {progress.speed:.2f}x"
            if progress.speed is not None
            else "Speed: —"
        )

    def _handle_export_variant_finished(self, variant: ExportVariant) -> None:
        worker = self.sender()

        if not isinstance(worker, _ExportVariantWorker):
            return

        job_id = worker.job_id
        self._generating_export_variant_job_ids.discard(job_id)

        existing = self._job_store.get_export_variants(job_id)
        variants = list(existing.variants) if existing is not None else []
        variants.append(variant)

        self._job_store.set_export_variants(
            job_id, ExportVariantCollection(variants=variants)
        )

        if job_id == self._job_id:
            self._on_change()

    def _handle_export_variant_failed(self, message: str) -> None:
        worker = self.sender()

        if not isinstance(worker, _ExportVariantWorker):
            return

        job_id = worker.job_id
        self._generating_export_variant_job_ids.discard(job_id)

        job = self._job_store.get(job_id)

        if job is None:
            return

        if job_id == self._job_id:
            self._record_error(
                job,
                f"Export variant generation failed: {message}",
                on_retry=lambda: self._execute_export_variant_generation(
                    job,
                    render_result=worker.render_result,
                    orientation=worker.orientation,
                    platform=worker.platform,
                ),
            )
        else:
            job.errors.append(f"Export variant generation failed: {message}")

    def _handle_export_variant_thread_finished(self) -> None:
        """
        Drop the (thread, worker) bookkeeping entry once the QThread
        has actually stopped.

        Bound-method connection for the same cross-thread-safety
        reason as the worker signals above - self.sender() here is
        the QThread instance itself, which carries job_id as a plain
        attribute (set above) since this signal has no arguments to
        carry it as a parameter.
        """

        thread = self.sender()
        job_id = getattr(thread, "job_id", None)

        if job_id is not None:
            self._export_variant_threads.pop(job_id, None)

    def _handle_stop_export_variant_generation(self) -> None:
        if self._job_id is None:
            return

        entry = self._export_variant_threads.get(self._job_id)

        if entry is None:
            return

        _thread, worker = entry
        worker.request_cancel()

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
                    target_audience=_audience_fallback(job),
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

        render_result = resolve_effective_render_orchestration_result(
            job, self._job_store.get_render_result(self._job_id)
        )
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

    def _all_generation_threads(self) -> list[QThread]:
        return (
            [thread for thread, _worker in self._export_variant_threads.values()]
            + [thread for thread, _worker in self._title_card_threads.values()]
            + [thread for thread, _worker in self._subtitle_threads.values()]
        )

    def has_pending_generations(self) -> bool:
        """
        Return whether any export-variant or title-card QThread is
        still genuinely running.

        Checks QThread.isFinished() directly rather than the thread
        dicts' own membership - an entry is only popped by the
        queued thread.finished signal, so dict membership alone would
        report "still pending" after a thread has actually stopped, for
        as long as nothing has pumped the event loop since (same
        reasoning as RenderWorkspaceView.has_pending_renders).
        """

        return any(not thread.isFinished() for thread in self._all_generation_threads())

    def cancel_pending_generations(self) -> None:
        """
        Ask every in-flight export-variant/title-card FFmpeg pass to
        stop. Unlike the main render (RenderOrchestratorService has no
        cancellation path at all), these two have real cancellation
        support, so closing the app can stop them promptly instead of
        waiting out a multi-minute pass.
        """

        for _thread, worker in list(self._export_variant_threads.values()):
            worker.request_cancel()

        for _thread, title_card_worker in list(self._title_card_threads.values()):
            title_card_worker.request_cancel()

        for _thread, subtitle_worker in list(self._subtitle_threads.values()):
            subtitle_worker.request_cancel()

    def wait_for_pending_generations(self, *, timeout_ms: int = 60_000) -> bool:
        """
        Block until every in-flight generation QThread has actually
        stopped, or timeout_ms elapses - never abandon a still-running
        one (destroying a QThread wrapper whose OS thread is still
        executing is a hard Qt-level crash, not a catchable error - see
        RenderWorkspaceView.wait_for_pending_renders for the full
        history).

        Interleaves short thread.wait() calls with processEvents()
        because the worker thread's own termination depends on a queued
        thread.quit signal that needs the calling thread's event loop
        pumped to ever be delivered - a bare wait() would self-deadlock.
        """

        app = QApplication.instance()
        deadline = time.monotonic() + (timeout_ms / 1000.0)

        while self.has_pending_generations():
            if time.monotonic() > deadline:
                return False

            for thread in self._all_generation_threads():
                thread.wait(20)

            if app is not None:
                app.processEvents()

        return True

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
