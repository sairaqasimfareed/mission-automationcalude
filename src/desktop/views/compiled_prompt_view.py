from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import button, card, small_muted, subheading
from src.models.video_job import VideoJob
from src.services.enriched_scene_prompt_service import EnrichedScenePromptService

_LEFT = Qt.AlignmentFlag.AlignLeft


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

        self._build_prompts_card(job)

    def _build_prompts_card(self, job: VideoJob) -> None:
        frame, layout = card(f"Compiled Prompts ({len(job.scenes)})", icon_name="tag")

        layout.addWidget(
            small_muted(
                "The full generation instruction for each scene - copy one "
                "and generate that clip manually elsewhere. This never "
                "changes what the app's own automated generation sends."
            )
        )

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        for scene in sorted(job.scenes, key=lambda item: item.scene_number):
            entry = self._enriched_scene_prompt_service.build_entry(
                job=job, scene=scene
            )

            row = QFrame()
            row.setProperty("sceneRow", True)

            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 12, 8)
            row_layout.setSpacing(4)

            row_layout.addWidget(subheading(f"#{scene.scene_number} {scene.title}"))

            text_area = QTextEdit()
            text_area.setReadOnly(True)
            text_area.setPlainText(entry.full_text())
            text_area.setMinimumHeight(160)
            row_layout.addWidget(text_area)

            copy_button = button("Copy prompt", icon_name="check")
            copy_button.clicked.connect(
                lambda _checked=False, prompt_entry=entry: (
                    self._handle_copy(prompt_entry.full_text())
                )
            )
            row_layout.addWidget(copy_button, alignment=_LEFT)

            layout.addWidget(row)

        self._layout.addWidget(frame)

    @staticmethod
    def _handle_copy(text: str) -> None:
        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(text)
