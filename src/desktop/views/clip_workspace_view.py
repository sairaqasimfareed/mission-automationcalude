from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.widgets import (
    badge,
    card,
    muted,
    small_muted,
    status_label,
    subheading,
)
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob


class ClipWorkspaceView(QWidget):
    """
    Clip Workspace: per-scene duration and resolved-clip review.

    Mission Automation plans one visual clip per scene, sized to that
    scene's estimated_duration_seconds - there is no scene-splitting
    backend capability yet (a scene always maps to exactly one
    VideoClip). This workspace is therefore a review surface: each
    scene's planned duration next to its resolved VideoClip (once
    assets are acquired via the Render Workspace) and any workflow
    warnings recorded on the job, so duration mismatches or acquisition
    problems are visible in one place rather than buried in the
    Render Workspace's per-scene decision cards.
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

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 12, 0, 0)
        self._layout.setSpacing(16)

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

        self._build_summary_card(job)
        self._build_clips_card(job)

    def _build_summary_card(self, job: VideoJob) -> None:
        frame, layout = card("Duration summary", icon_name="clapper")

        total_planned = sum(scene.estimated_duration_seconds for scene in job.scenes)
        total_resolved = sum(clip.duration_seconds for clip in job.video_clips)

        layout.addWidget(
            muted(
                f"{len(job.scenes)} scene(s) planned, "
                f"{total_planned}s total. "
                f"{len(job.video_clips)} clip(s) resolved, "
                f"{total_resolved}s total."
            )
        )

        duration_warnings = [
            warning for warning in job.warnings if "narration" in warning.lower()
        ]

        if duration_warnings:
            layout.addWidget(
                status_label(
                    "Duration warnings:\n"
                    + "\n".join(f"- {warning}" for warning in duration_warnings),
                    role="warning",
                )
            )

        self._layout.addWidget(frame)

    def _build_clips_card(self, job: VideoJob) -> None:
        frame, layout = card(f"Scenes ({len(job.scenes)})", icon_name="clapper")

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        clips_by_scene = {clip.scene_number: clip for clip in job.video_clips}

        for scene in job.scenes:
            row = QFrame()
            row.setProperty("sceneRow", True)

            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 12, 8)
            row_layout.setSpacing(4)

            row_layout.addWidget(
                subheading(
                    f"#{scene.scene_number} {scene.title} "
                    f"({scene.estimated_duration_seconds}s planned)"
                )
            )
            row_layout.addWidget(small_muted(scene.narration))

            clip = clips_by_scene.get(scene.scene_number)

            if clip is not None:
                row_layout.addLayout(self._clip_summary(clip))
            else:
                row_layout.addWidget(
                    small_muted("No resolved clip yet - see Render Workspace.")
                )

            layout.addWidget(row)

        self._layout.addWidget(frame)

    @staticmethod
    def _clip_summary(clip: VideoClip) -> QVBoxLayout:
        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(0, 4, 0, 0)
        summary_layout.setSpacing(2)

        summary_layout.addWidget(
            badge(f"{clip.source_type.value} · {clip.status.value}")
        )
        summary_layout.addWidget(
            small_muted(
                f"{clip.duration_seconds}s"
                f" · {clip.local_file or clip.source_url or 'no file yet'}"
            )
        )

        return summary_layout
