from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.notifications import notify_success
from src.desktop.scroll_preservation import keep_scroll_on_refresh
from src.desktop.widgets import (
    button,
    card,
    small_muted,
    status_label,
    subheading,
)
from src.models.enriched_scene_prompt import EnrichedScenePrompt
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.enriched_scene_prompt_service import EnrichedScenePromptService
from src.services.prompt_completeness_service import PromptCompletenessService
from src.services.prompt_edit_service import (
    keep_edit_against_current_prompt,
    reset_edit,
    save_edit,
)

_LEFT = Qt.AlignmentFlag.AlignLeft


class _PromptTextEdit(QTextEdit):
    """A prompt box that says when the operator clicks or tabs out of it, so the edit can be
    saved without a Save button."""

    focus_lost = Signal()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self.focus_lost.emit()


class CompiledPromptView(QWidget):
    """
    REQ-9 (full compiled prompt screen): per scene, the FULL compiled
    generation prompt - visual prompt, negative constraints,
    transitions, full continuity state, resolved reference assets,
    execution settings, quality scores - so the user can copy it and
    generate a clip manually elsewhere.

    Read-only and display-only - never mutates the job or anything
    the automated generation pipeline actually reads.
    EnrichedScenePromptService (the real assembly logic) is
    deliberately pure/deterministic (no LLM call, same as
    CinematicPromptCompilationService it builds on), so this view
    needs no QThread worker, unlike the real generation flows
    elsewhere in ClipWorkspaceView.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        on_change: Callable[[], None],
        enriched_scene_prompt_service: EnrichedScenePromptService | None = None,
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_change = on_change
        self._job_id: UUID | None = None

        self._enriched_scene_prompt_service = (
            enriched_scene_prompt_service or EnrichedScenePromptService()
        )

        self._completeness_service = PromptCompletenessService(
            self._enriched_scene_prompt_service
        )

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
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_prompts_card(job)

    def _build_prompts_card(self, job: VideoJob) -> None:
        frame, layout = card(f"Compiled Prompts ({len(job.scenes)})", icon_name="tag")

        layout.addWidget(
            small_muted(
                "The full generation instruction for each scene - copy one "
                "and generate that clip manually elsewhere. You can edit any "
                "prompt: click away from the box and it is saved, and that text "
                "is then what the app sends for that scene instead of the "
                "automatic one. Reset to automatic goes back to the generated text."
            )
        )

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        # Wording a clip generated on its own cannot use ("Same village", "unspecified", a
        # prompt too short to describe the place): reported here, before credits are spent.
        report = self._completeness_service.report(job)

        if not report.checked:
            pass
        elif report.is_complete:
            layout.addWidget(
                status_label(
                    "Every prompt names its place, light and action in full.",
                    role="success",
                )
            )
        else:
            numbers = ", ".join(str(n) for n in report.flagged_scene_numbers)
            layout.addWidget(
                status_label(
                    f"{len(report.flagged_scene_numbers)} scene(s) have a thin prompt "
                    f"- scenes {numbers}. Details are under each one below.",
                    role="warning",
                )
            )

        for scene in sorted(job.scenes, key=lambda item: item.scene_number):
            entries = self._enriched_scene_prompt_service.build_entries(
                job=job, scene=scene
            )
            total_entries = len(entries)

            for entry in entries:
                row = QFrame()
                row.setProperty("sceneRow", True)

                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(12, 8, 12, 8)
                row_layout.setSpacing(4)

                heading_text = f"#{scene.scene_number} {scene.title}"

                if total_entries > 1:
                    heading_text += (
                        f" - Part {entry.clip_sequence_index + 1} of {total_entries}"
                    )

                row_layout.addWidget(subheading(heading_text))

                for finding in report.findings_for(
                    scene.scene_number, entry.clip_sequence_index
                ):
                    row_layout.addWidget(status_label(finding.message, role="warning"))

                self._add_prompt_editor(job, scene, entry, row_layout)

                layout.addWidget(row)

        self._layout.addWidget(frame)

    def _add_prompt_editor(
        self,
        job: VideoJob,
        scene: Scene,
        entry: EnrichedScenePrompt,
        row_layout: QVBoxLayout,
    ) -> None:
        """The editable prompt box for one scene / part, saved when the operator clicks away,
        with Copy and "Reset to automatic" beside it. Only the prompt text is editable; the rest
        (negative constraints, continuity, references, settings) is shown below, read-only.
        """

        scene_number = scene.scene_number
        clip_index = entry.clip_sequence_index
        state = {"saved_text": entry.editable_text}

        text_area = _PromptTextEdit()
        text_area.setAcceptRichText(False)
        text_area.setPlainText(entry.editable_text)
        text_area.setMinimumHeight(160)
        row_layout.addWidget(text_area)

        status = status_label("", role="warning")
        row_layout.addWidget(status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        copy_button = button("Copy prompt", icon_name="check")
        reset_button = button("Reset to automatic")
        keep_button = button("Keep mine", variant="ghost")
        buttons.addWidget(copy_button)
        buttons.addWidget(reset_button)
        buttons.addWidget(keep_button)
        buttons.addStretch()
        row_layout.addLayout(buttons)

        def show_state(*, edited: bool, stale: bool) -> None:
            status.setVisible(edited)
            reset_button.setEnabled(edited)
            keep_button.setVisible(edited and stale)
            status.setText(
                "Edited by you - the automatic prompt has changed since. Reset to automatic "
                "to use the new one, or Keep mine."
                if stale
                else "Edited by you - this text is sent instead of the automatic prompt."
            )

        show_state(edited=entry.is_edited, stale=entry.edit_is_stale)

        def save_now() -> None:
            text = text_area.toPlainText()

            if text == state["saved_text"]:
                return

            kept = save_edit(
                job, scene_number, clip_index, text, automatic_text=entry.automatic_text
            )
            self._job_store.add(job)
            state["saved_text"] = text
            show_state(edited=kept, stale=False)
            notify_success("Prompt saved" if kept else "Back to the automatic prompt")

        def reset_now() -> None:
            reset_edit(job, scene_number, clip_index)
            self._job_store.add(job)
            notify_success("Prompt reset to automatic")
            self.refresh(job)

        def keep_now() -> None:
            keep_edit_against_current_prompt(
                job, scene_number, clip_index, entry.automatic_text
            )
            self._job_store.add(job)
            show_state(edited=True, stale=False)

        def copy_now() -> None:
            save_now()
            fresh = next(
                (
                    candidate
                    for candidate in self._enriched_scene_prompt_service.build_entries(
                        job=job, scene=scene
                    )
                    if candidate.clip_sequence_index == clip_index
                ),
                entry,
            )
            self._handle_copy(fresh.full_text())

        text_area.focus_lost.connect(save_now)
        reset_button.clicked.connect(lambda _checked=False: reset_now())
        keep_button.clicked.connect(lambda _checked=False: keep_now())
        copy_button.clicked.connect(lambda _checked=False: copy_now())

        details = entry.details_text()

        if details:
            details_area = QTextEdit()
            details_area.setReadOnly(True)
            details_area.setPlainText(details)
            details_area.setMinimumHeight(110)
            row_layout.addWidget(small_muted("Sent with it (not editable):"))
            row_layout.addWidget(details_area)

    @staticmethod
    def _handle_copy(text: str) -> None:
        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(text)
