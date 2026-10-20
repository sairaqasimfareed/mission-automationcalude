"""The Brighter picture option: no vignette, the moody grade with its shadows lifted. The stored timeline is
never touched (the change is made on a copy at render time)."""

from __future__ import annotations

from src.models.picture_brightness import PictureBrightness
from src.models.video_job import VideoJob
from src.services.render_speed_rules import timeline_for_picture_brightness
from tests.test_genre_timeline_pipeline_service import (
    build_clip,
    build_scene,
    pipeline,
)


def _job(brightness: PictureBrightness) -> VideoJob:
    job = VideoJob(
        project_name="P",
        channel_name="C",
        niche="n",
        topic="t",
        genre_id="genre.mystery",
    )
    job.picture_brightness = brightness

    return job


def _mystery_timeline():  # type: ignore[no-untyped-def]
    return pipeline.build(
        scenes=[build_scene(scene_number=1, duration_seconds=8)],
        clips=[build_clip(scene_number=1, duration_seconds=8)],
        genre_id="genre.mystery",
    ).timeline


def _effect_ids(timeline) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        effect.preset.resolved_preset_id
        for item in timeline.items
        if item.editing_blueprint is not None
        for effect in item.editing_blueprint.visual_effects
    ]


def test_the_standard_look_is_left_exactly_as_it_is() -> None:
    timeline = _mystery_timeline()

    assert (
        timeline_for_picture_brightness(_job(PictureBrightness.STANDARD), timeline)
        is timeline
    )


def test_brighter_drops_the_vignette_and_lifts_the_moody_grade_on_a_copy() -> None:
    timeline = _mystery_timeline()
    before = _effect_ids(timeline)

    brighter = timeline_for_picture_brightness(
        _job(PictureBrightness.BRIGHTER), timeline
    )
    after = _effect_ids(brighter)

    assert "visual.vignette_soft" in before
    assert "visual.vignette_soft" not in after
    assert "visual.lut_moody_desaturated" in before
    assert "visual.lut_moody_lifted" in after
    assert "visual.lut_moody_desaturated" not in after
    # the stored timeline keeps its own look
    assert _effect_ids(timeline) == before


def test_the_lifted_grade_raises_the_shadows_with_gamma_and_the_old_grade_is_unchanged() -> (
    None
):
    from src.models.render_graph import (
        RenderNode,
        RenderNodeStatus,
        RenderNodeType,
    )
    from tests.test_video_filter_translation_service import (
        _visual_payload,
        capabilities,
        service,
    )

    def eq_options(preset_id: str) -> dict[str, str]:
        node = RenderNode(
            node_type=RenderNodeType.VISUAL_EFFECT,
            status=RenderNodeStatus.READY,
            scene_number=1,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
            duration_seconds=8.0,
            payload=_visual_payload(preset_id),
        )
        translation = service.translate_scene_node(
            render_node=node,
            input_label="a",
            output_label="b",
            width=720,
            height=1280,
            frame_rate=30.0,
            capabilities=capabilities,
        )

        return next(f.options for f in translation.filters if f.filter_name == "eq")

    assert "gamma" not in eq_options("visual.lut_moody_desaturated")
    assert float(eq_options("visual.lut_moody_lifted")["gamma"]) > 1.0


def test_choosing_brighter_in_the_render_tab_is_kept_on_the_job() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QComboBox

    from src.desktop.job_store import InMemoryJobStore
    from src.desktop.views.render_workspace_view import RenderWorkspaceView

    app = QApplication.instance() or QApplication([])
    assert app is not None
    store = InMemoryJobStore()
    job = _job(PictureBrightness.STANDARD)
    store.add(job)
    view = RenderWorkspaceView(
        job_store=store,
        render_runtime_factory=object(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    combo = next(
        c
        for c in view.findChildren(QComboBox)
        if any(c.itemData(i) == PictureBrightness.BRIGHTER for i in range(c.count()))
    )
    combo.setCurrentIndex(combo.findData(PictureBrightness.BRIGHTER))
    QCoreApplication.processEvents()

    assert store.get(job.id).picture_brightness == PictureBrightness.BRIGHTER
