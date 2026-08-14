from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import badge, button, card, muted, small_muted, subheading
from src.models.editing_directives import (
    CameraDirective,
    MusicDirective,
    SceneEditingDirectives,
    TransitionDirective,
)
from src.models.effect_registry import EffectCategory
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.video_timeline_item import VideoTimelineItem
from src.services.effect_registry_service import EffectRegistryService

_LEFT = Qt.AlignmentFlag.AlignLeft

_NO_OVERRIDE = "(genre default)"
_NO_MUSIC = "(no music - disable)"

_registry = EffectRegistryService.with_default_presets()

_CAMERA_CHOICES = [_NO_OVERRIDE] + [
    preset.preset_id
    for preset in _registry.list_by_category(EffectCategory.CAMERA)
    if preset.preset_id != "camera.none"
]

_TRANSITION_CHOICES = [_NO_OVERRIDE] + [
    preset.preset_id
    for preset in _registry.list_by_category(EffectCategory.TRANSITION)
    if preset.preset_id != "transition.cut"
]

_MUSIC_CHOICES = [_NO_OVERRIDE, _NO_MUSIC] + [
    preset.preset_id
    for preset in _registry.list_by_category(EffectCategory.MUSIC)
    if preset.preset_id != "music.none"
]


class EditingTimelineView(QWidget):
    """
    Editing Timeline: per-scene creative overrides and the resolved
    video timeline in playback order.

    VideoTimeline is built automatically from genre-resolved editing
    directives during render (GenreTimelinePipelineService /
    TimelineBuilderService). Scene overrides saved here are stored on
    VideoJob.scene_editing_overrides and passed as
    overrides_by_scene into ProjectRenderRuntimeFactory.build() on the
    next render, replacing the genre default for that one scene
    (GenreDirectiveGenerationService.apply_overrides handles the
    merge - only non-default fields on the override actually replace
    the genre default, so leaving a control on "(genre default)"
    changes nothing for that field).
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

        self._build_overrides_card(job)
        self._build_timeline_card(job)

    def _build_overrides_card(self, job: VideoJob) -> None:
        frame, layout = card("Scene overrides", icon_name="clapper")

        if not job.scenes:
            layout.addWidget(
                small_muted("Plan scenes in Content Studio to set overrides.")
            )
            self._layout.addWidget(frame)

            return

        layout.addWidget(
            small_muted(
                "Override camera motion, transitions, or music for one "
                "scene. Unchanged controls keep the genre default. "
                "Overrides apply the next time this project is "
                "rendered."
            )
        )

        for scene in sorted(job.scenes, key=lambda item: item.scene_number):
            layout.addLayout(self._override_row(job, scene))

        self._layout.addWidget(frame)

    def _override_row(self, job: VideoJob, scene: Scene) -> QVBoxLayout:
        row_layout = QVBoxLayout()
        row_layout.setContentsMargins(0, 4, 0, 4)
        row_layout.setSpacing(4)

        existing = job.scene_editing_overrides.get(scene.scene_number)

        row_layout.addWidget(subheading(f"Scene {scene.scene_number}: {scene.title}"))

        if existing is not None:
            row_layout.addWidget(badge("override saved"))

        form = QFormLayout()
        form.setSpacing(6)

        camera_select = QComboBox()
        camera_select.addItems(_CAMERA_CHOICES)
        if existing is not None and existing.camera.preset_id in _CAMERA_CHOICES:
            camera_select.setCurrentText(existing.camera.preset_id)
        form.addRow("Camera", camera_select)

        transition_in_select = QComboBox()
        transition_in_select.addItems(_TRANSITION_CHOICES)
        if (
            existing is not None
            and existing.transition_in.preset_id in _TRANSITION_CHOICES
        ):
            transition_in_select.setCurrentText(existing.transition_in.preset_id)
        form.addRow("Transition in", transition_in_select)

        transition_out_select = QComboBox()
        transition_out_select.addItems(_TRANSITION_CHOICES)
        if (
            existing is not None
            and existing.transition_out.preset_id in _TRANSITION_CHOICES
        ):
            transition_out_select.setCurrentText(existing.transition_out.preset_id)
        form.addRow("Transition out", transition_out_select)

        music_select = QComboBox()
        music_select.addItems(_MUSIC_CHOICES)
        if existing is not None:
            if existing.music.enabled is False:
                music_select.setCurrentText(_NO_MUSIC)
            elif existing.music.preset_id in _MUSIC_CHOICES:
                music_select.setCurrentText(existing.music.preset_id)
        form.addRow("Music", music_select)

        row_layout.addLayout(form)

        button_row = QHBoxLayout()

        save_button = button("Save override", variant="primary", icon_name="check")
        save_button.clicked.connect(
            lambda: self._handle_save_override(
                scene_number=scene.scene_number,
                camera_select=camera_select,
                transition_in_select=transition_in_select,
                transition_out_select=transition_out_select,
                music_select=music_select,
            )
        )
        button_row.addWidget(save_button)

        if existing is not None:
            clear_button = button(
                "Clear override", variant="ghost", icon_name="x-circle"
            )
            clear_button.clicked.connect(
                lambda: self._handle_clear_override(scene.scene_number)
            )
            button_row.addWidget(clear_button)

        button_row.addStretch(1)
        row_layout.addLayout(button_row)

        return row_layout

    def _handle_save_override(
        self,
        *,
        scene_number: int,
        camera_select: QComboBox,
        transition_in_select: QComboBox,
        transition_out_select: QComboBox,
        music_select: QComboBox,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        camera = (
            CameraDirective()
            if camera_select.currentText() == _NO_OVERRIDE
            else CameraDirective(preset_id=camera_select.currentText())
        )

        transition_in = (
            TransitionDirective()
            if transition_in_select.currentText() == _NO_OVERRIDE
            else TransitionDirective(
                preset_id=transition_in_select.currentText(),
                duration_seconds=0.6,
            )
        )

        transition_out = (
            TransitionDirective()
            if transition_out_select.currentText() == _NO_OVERRIDE
            else TransitionDirective(
                preset_id=transition_out_select.currentText(),
                duration_seconds=0.6,
            )
        )

        music_choice = music_select.currentText()

        if music_choice == _NO_OVERRIDE:
            music = MusicDirective()
        elif music_choice == _NO_MUSIC:
            music = MusicDirective(preset_id="music.none", enabled=False)
        else:
            music = MusicDirective(preset_id=music_choice)

        job.scene_editing_overrides[scene_number] = SceneEditingDirectives(
            scene_number=scene_number,
            camera=camera,
            transition_in=transition_in,
            transition_out=transition_out,
            music=music,
        )
        self._on_change()

    def _handle_clear_override(self, scene_number: int) -> None:
        job = self._current_job()

        if job is None:
            return

        job.scene_editing_overrides.pop(scene_number, None)
        self._on_change()

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
            blueprint = item.editing_blueprint

            transition_in = blueprint.transition_in.preset.resolved_preset_id
            transition_out = blueprint.transition_out.preset.resolved_preset_id
            row_layout.addWidget(
                small_muted(f"Transitions: {transition_in} in / {transition_out} out")
            )

            camera_id = blueprint.camera.preset.resolved_preset_id
            row_layout.addWidget(
                small_muted(f"Camera: {camera_id} ({blueprint.camera.intensity.value})")
            )

            if blueprint.visual_effects:
                effect_descriptions = ", ".join(
                    f"{effect.preset.resolved_preset_id} " f"({effect.intensity.value})"
                    for effect in blueprint.visual_effects
                )
                row_layout.addWidget(
                    small_muted(f"Visual effects: {effect_descriptions}")
                )
            else:
                row_layout.addWidget(small_muted("Visual effects: none"))

        return row_layout

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)
