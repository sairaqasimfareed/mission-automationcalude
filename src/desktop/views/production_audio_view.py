from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.widgets import badge, card, muted, small_muted, subheading
from src.models.audio_track import AudioTrack
from src.models.video_job import VideoJob


class ProductionAudioView(QWidget):
    """
    Production Audio: voiceover status and the resolved audio timeline
    (voiceover, background music, sound effects).

    Voice generation currently runs as one of RenderOrchestratorService's
    registered pipeline stages inside a single render call - there is
    no standalone "generate voice only" trigger in the backend yet, so
    this workspace reviews what the render produced rather than
    offering its own generation button (the Render Workspace triggers
    the render that produces this).
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

        self._build_voice_card(job)
        self._build_timeline_card(job)

    def _build_voice_card(self, job: VideoJob) -> None:
        frame, layout = card("Voiceover", icon_name="audio")

        layout.addWidget(
            badge(f"{job.voice_strategy.value} · {job.voice_status.value}")
        )

        if job.voice_provider:
            layout.addWidget(small_muted(f"Provider: {job.voice_provider}"))

        if job.voice_file:
            layout.addWidget(small_muted(f"File: {job.voice_file}"))
        else:
            layout.addWidget(
                small_muted(
                    "No voiceover file yet - run render in the Render "
                    "Workspace to generate it."
                )
            )

        self._layout.addWidget(frame)

    def _build_timeline_card(self, job: VideoJob) -> None:
        frame, layout = card("Audio timeline", icon_name="audio")

        timeline = job.audio_timeline

        if timeline is None or not timeline.tracks:
            layout.addWidget(small_muted("No audio timeline yet."))
            self._layout.addWidget(frame)

            return

        layout.addWidget(
            muted(
                f"{len(timeline.tracks)} track(s), "
                f"{timeline.total_duration_seconds:.1f}s total, "
                f"{timeline.sample_rate}Hz / {timeline.channels}ch."
            )
        )

        for track in timeline.tracks:
            layout.addLayout(self._track_row(track))

        self._layout.addWidget(frame)

    @staticmethod
    def _track_row(track: AudioTrack) -> QVBoxLayout:
        row_layout = QVBoxLayout()
        row_layout.setContentsMargins(0, 4, 0, 4)
        row_layout.setSpacing(2)

        row_layout.addWidget(subheading(track.track_type.value))
        row_layout.addWidget(
            small_muted(
                f"{track.start_time_seconds:.1f}s - "
                f"{track.start_time_seconds + track.duration_seconds:.1f}s "
                f"· volume {track.volume:.2f} · {track.source_file}"
            )
        )

        return row_layout
