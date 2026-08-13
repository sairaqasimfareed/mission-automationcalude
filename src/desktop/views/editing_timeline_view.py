from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.widgets import badge, card, muted, small_muted, subheading
from src.models.video_job import VideoJob
from src.models.video_timeline_item import VideoTimelineItem


class EditingTimelineView(QWidget):
    """
    Editing Timeline: the resolved video timeline in playback order.

    VideoTimeline is built automatically from genre-resolved editing
    directives during render (GenreTimelinePipelineService /
    TimelineBuilderService) - there is no manual per-clip timeline
    editor in the backend yet, so this workspace visualizes the
    resolved result (clip placement, timing, transitions) rather than
    offering editing controls that would have nothing to write to.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_change = on_change
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

        self._build_timeline_card(job)

    def _build_timeline_card(self, job: VideoJob) -> None:
        frame, layout = card("Video timeline", icon_name="timeline")

        timeline = job.video_timeline

        if timeline is None:
            layout.addWidget(
                small_muted(
                    "No timeline yet - run render in the Render Workspace "
                    "to build it."
                )
            )
            self._layout.addWidget(frame)

            return

        layout.addWidget(
            muted(
                f"{timeline.total_duration_seconds:.1f}s total · "
                f"{timeline.output_resolution} @ {timeline.frame_rate}fps"
            )
        )

        ordered_items = timeline.ordered_items()

        if not ordered_items:
            layout.addWidget(small_muted("No timeline items placed yet."))
            self._layout.addWidget(frame)

            return

        for item in ordered_items:
            layout.addLayout(self._item_row(item))

        self._layout.addWidget(frame)

    @staticmethod
    def _item_row(item: VideoTimelineItem) -> QVBoxLayout:
        row_layout = QVBoxLayout()
        row_layout.setContentsMargins(0, 4, 0, 4)
        row_layout.setSpacing(2)

        row_layout.addWidget(
            subheading(
                f"Scene {item.scene_number} "
                f"({item.start_time_seconds:.1f}s - {item.end_time_seconds:.1f}s)"
            )
        )
        row_layout.addWidget(
            badge(f"{item.clip.source_type.value} · track {item.track_index}")
        )

        if item.editing_blueprint is not None:
            transition_in = (
                item.editing_blueprint.transition_in.preset.resolved_preset_id
            )
            transition_out = (
                item.editing_blueprint.transition_out.preset.resolved_preset_id
            )
            row_layout.addWidget(
                small_muted(f"Transitions: {transition_in} in / {transition_out} out")
            )

        return row_layout
