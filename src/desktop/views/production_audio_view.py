from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    badge,
    button,
    card,
    muted,
    small_muted,
    status_label,
    subheading,
)
from src.models.audio_generation_summary import (
    AudioComponentStatus,
    AudioGenerationSummary,
)
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.video_job import VideoJob
from src.services.media_generation_pipeline import MediaGenerationPipeline

_LEFT = Qt.AlignmentFlag.AlignLeft

_COMPONENT_STATUS_ROLE = {
    AudioComponentStatus.REUSED: "success",
    AudioComponentStatus.GENERATED: "success",
    AudioComponentStatus.SKIPPED: "warning",
    AudioComponentStatus.MANUAL_REQUIRED: "warning",
    AudioComponentStatus.FAILED: "error",
}


class ProductionAudioView(QWidget):
    """
    Production Audio: standalone voice/timeline/music/sound-effect
    generation, plus a review of the resulting audio timeline.

    Each stage below calls MediaGenerationPipeline directly - the same
    underlying services RenderOrchestratorService's Voice/Music/
    SoundEffect pipeline stages call internally during a full render,
    just callable one at a time without running an entire render.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        media_generation_pipeline: MediaGenerationPipeline,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._media_generation_pipeline = media_generation_pipeline
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._last_audio_summary: AudioGenerationSummary | None = None

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

        self._build_generation_card(job)
        self._build_summary_card()
        self._build_voice_card(job)
        self._build_timeline_card(job)

    def _build_generation_card(self, job: VideoJob) -> None:
        frame, layout = card("Media generation", icon_name="audio")

        layout.addWidget(
            small_muted(
                "Generate narration, build the editing timeline, then add "
                "background music and sound effects - each step runs on its "
                "own, without a full render."
            )
        )

        voice_button = button(
            "Generate voiceover", variant="primary", icon_name="audio"
        )
        voice_button.setEnabled(bool(job.scenes))
        voice_button.clicked.connect(self._handle_run_voice)
        layout.addWidget(voice_button, alignment=_LEFT)

        timeline_button = button(
            "Build editing timeline", variant="primary", icon_name="clapper"
        )
        timeline_button.setEnabled(bool(job.scenes) and bool(job.video_clips))
        timeline_button.clicked.connect(self._handle_run_timeline)
        layout.addWidget(timeline_button, alignment=_LEFT)

        music_button = button(
            "Generate background music", variant="primary", icon_name="audio"
        )
        music_button.setEnabled(job.video_timeline is not None)
        music_button.clicked.connect(self._handle_run_music)
        layout.addWidget(music_button, alignment=_LEFT)

        sound_effect_button = button(
            "Generate sound effects", variant="primary", icon_name="audio"
        )
        sound_effect_button.setEnabled(job.video_timeline is not None)
        sound_effect_button.clicked.connect(self._handle_run_sound_effects)
        layout.addWidget(sound_effect_button, alignment=_LEFT)

        layout.addWidget(
            small_muted(
                "Or coordinate all four in one action - reuses whatever is "
                "already valid and reports each component's outcome "
                "individually rather than stopping at the first problem."
            )
        )

        all_audio_button = button(
            "Generate all audio", variant="primary", icon_name="audio"
        )
        all_audio_button.setEnabled(bool(job.scenes) and bool(job.video_clips))
        all_audio_button.clicked.connect(self._handle_run_all_audio)
        layout.addWidget(all_audio_button, alignment=_LEFT)

        self._layout.addWidget(frame)

    def _build_summary_card(self) -> None:
        summary = self._last_audio_summary

        if summary is None:
            return

        frame, layout = card("Last 'Generate all audio' run", icon_name="audio")

        for result in summary.results:
            layout.addWidget(badge(f"{result.component} · {result.status.value}"))
            layout.addWidget(
                status_label(result.detail, role=_COMPONENT_STATUS_ROLE[result.status])
            )

        self._layout.addWidget(frame)

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
                    "No voiceover file yet - use Generate voiceover above, or "
                    "run render in the Render Workspace."
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

        directive_summary = ProductionAudioView._directive_summary(track)

        if directive_summary:
            row_layout.addWidget(small_muted(directive_summary))

        return row_layout

    @staticmethod
    def _directive_summary(track: AudioTrack) -> str | None:
        """
        Summarize the creative directive that produced this track.

        Voiceover tracks carry the resolved voice blueprint's
        emotion/pace/energy/speed (set by VoiceGenerationService);
        music and sound-effect tracks carry the resolved preset and
        library query (set by MusicGenerationService/
        SoundEffectGenerationService). Neither was previously shown
        anywhere - only the resulting audio file path was.
        """

        metadata = track.metadata

        if track.track_type == AudioTrackType.VOICEOVER:
            parts = [
                f"{label}: {metadata[key]}"
                for label, key in (
                    ("emotion", "emotion"),
                    ("pace", "pace"),
                    ("energy", "energy"),
                    ("speed", "speed"),
                )
                if key in metadata
            ]
        else:
            parts = [
                f"{label}: {metadata[key]}"
                for label, key in (
                    ("preset", "resolved_preset_id"),
                    ("intensity", "intensity"),
                    ("query", "library_query"),
                )
                if key in metadata
            ]

        return " · ".join(parts) if parts else None

    def _handle_run_voice(self) -> None:
        self._run_stage(self._media_generation_pipeline.run_voice, "Voice generation")

    def _handle_run_timeline(self) -> None:
        self._run_stage(
            self._media_generation_pipeline.run_timeline, "Timeline generation"
        )

    def _handle_run_music(self) -> None:
        self._run_stage(self._media_generation_pipeline.run_music, "Music generation")

    def _handle_run_sound_effects(self) -> None:
        self._run_stage(
            self._media_generation_pipeline.run_sound_effects,
            "Sound effect generation",
        )

    def _handle_run_all_audio(self) -> None:
        job = self._current_job()

        if job is None:
            return

        summary = self._media_generation_pipeline.run_all_audio(job)
        self._last_audio_summary = summary

        for result in summary.failed_components:
            job.errors.append(f"{result.component} generation failed: {result.detail}")

        self._on_change()

    def _run_stage(self, stage: Callable[[VideoJob], VideoJob], label: str) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            stage(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"{label} failed: {error}",
                on_retry=lambda: self._run_stage(stage, label),
            )

            return

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
