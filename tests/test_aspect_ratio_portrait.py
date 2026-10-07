"""
Video shape (16:9 / 9:16), 2026-10-07. Chosen when a project is created; a 9:16 project
tells Muse - in words, at the end of every clip prompt - to make true vertical video,
sets Flow's own aspect control, gives shot planning tall-frame advice, renders at a
portrait size, and keeps the export variants working from a vertical master.

Live evidence behind the sentence: "Resolution 9:16." came back as a 16:9 picture with
blurred bars top and bottom; the explicit sentence returned true 720x1280 vertical clips.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import _render_size  # noqa: E402
from src.desktop.views.project_form_view import ProjectFormView  # noqa: E402
from src.desktop.views.render_workspace_view import RenderWorkspaceView  # noqa: E402
from src.models.specification_enums import AspectRatio  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.video_provider import VideoProvider  # noqa: E402
from src.services.export_variant_render_service import (  # noqa: E402
    ExportVariantRenderService,
)
from src.services.shot_planning_service import ShotPlanningService  # noqa: E402
from src.services.video_provider_rules import (  # noqa: E402
    MUSE_PORTRAIT_SENTENCE,
    rules_for,
)
from tests.test_export_variant_render_service import (  # noqa: E402
    _render_result,
    _service,
)
from tests.test_project_form_view import (  # noqa: E402
    _view as _form_view,
)
from tests.test_project_form_view import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)

_PROMPT = "Identity: honey. Environment: Kitchen. Duration: 8 seconds."
_MUSE = rules_for(VideoProvider.MUSE)
_FLOW = rules_for(VideoProvider.GOOGLE_FLOW)


def _job(
    aspect: AspectRatio = AspectRatio.LANDSCAPE, size: str = "1920x1080"
) -> VideoJob:
    return VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        aspect_ratio=aspect,
        output_resolution=size,
    )


# ------------------------------------------------------------------ the field


def test_a_project_is_landscape_unless_chosen_otherwise() -> None:
    assert _job().aspect_ratio == AspectRatio.LANDSCAPE
    assert _job().nominal_clip_resolution == "1920x1080"


def test_a_vertical_project_records_vertical_clip_sizes() -> None:
    assert _job(AspectRatio.PORTRAIT).nominal_clip_resolution == "1080x1920"


def test_the_shape_survives_saving_and_a_project_saved_before_it_still_loads() -> None:
    job = _job(AspectRatio.PORTRAIT, "1080x1920")

    assert VideoJob.model_validate_json(job.model_dump_json()).aspect_ratio == (
        AspectRatio.PORTRAIT
    )

    data = job.model_dump(mode="json")
    data.pop("aspect_ratio")

    assert VideoJob.model_validate(data).aspect_ratio == AspectRatio.LANDSCAPE


# ----------------------------------------------------------------- the prompt


def test_muse_is_told_to_make_true_vertical_video_at_the_end_of_the_prompt() -> None:
    text = _MUSE.finalize_prompt(_PROMPT, 8.0, AspectRatio.PORTRAIT)

    assert text.endswith(MUSE_PORTRAIT_SENTENCE)
    assert "Duration: 8 seconds." in text
    assert "no blurred bars" in MUSE_PORTRAIT_SENTENCE
    assert "fully inside the frame" in MUSE_PORTRAIT_SENTENCE


def test_the_sentence_is_the_one_the_operator_confirmed_in_muse() -> None:
    assert MUSE_PORTRAIT_SENTENCE == (
        "Vertical 9:16 portrait video, true full-frame vertical composition, no crop, "
        "no letterbox, no blurred bars. Compose natively for vertical: main subject "
        "centered and fully inside the frame."
    )


def test_a_landscape_project_adds_nothing_to_a_prompt() -> None:
    assert _MUSE.finalize_prompt(_PROMPT, 8.0, AspectRatio.LANDSCAPE) == (
        _MUSE.finalize_prompt(_PROMPT, 8.0)
    )
    assert "9:16" not in _MUSE.finalize_prompt(_PROMPT, 8.0)


def test_flow_gets_no_sentence_it_uses_its_own_aspect_control() -> None:
    assert "9:16" not in _FLOW.finalize_prompt(_PROMPT, 8.0, AspectRatio.PORTRAIT)


# ------------------------------------------------------------- shot planning


def test_shot_planning_gets_tall_frame_advice_for_a_vertical_project() -> None:
    from src.models.scene import Scene
    from src.models.visual_continuity import VisualContinuityBible

    scenes = [
        Scene(
            scene_number=1,
            title="Scene 1",
            narration="Honey in a kitchen.",
            visual_prompt="Honey.",
            estimated_duration_seconds=8,
        )
    ]
    bible = VisualContinuityBible(script_lock_hash="a" * 64)

    portrait = ShotPlanningService._build_prompt(  # noqa: SLF001
        scenes, bible, "Honey", AspectRatio.PORTRAIT
    )
    landscape = ShotPlanningService._build_prompt(
        scenes, bible, "Honey"
    )  # noqa: SLF001

    assert "VERTICAL 9:16" in portrait
    assert "centre the main subject" in portrait
    assert "VERTICAL" not in landscape


# -------------------------------------------------------------- the new form


def test_the_new_project_form_offers_the_shape_with_16_9_as_the_default(
    qapp: QApplication,  # noqa: F811
) -> None:
    view = _form_view()
    combo = view._aspect_ratio  # noqa: SLF001

    assert [combo.itemData(i) for i in range(combo.count())] == [
        AspectRatio.LANDSCAPE,
        AspectRatio.PORTRAIT,
    ]
    assert combo.currentData() == AspectRatio.LANDSCAPE


def _create(view: ProjectFormView, aspect_index: int) -> VideoJob:
    view._project_name.setText("Remedy")  # noqa: SLF001
    view._channel_name.setText("Channel")  # noqa: SLF001
    view._topic.setText("Honey for coughs")  # noqa: SLF001
    view._video_type.setText("Explainer")  # noqa: SLF001
    view._niche.setText("health")  # noqa: SLF001
    view._aspect_ratio.setCurrentIndex(aspect_index)  # noqa: SLF001
    view._handle_create_clicked()  # noqa: SLF001
    store = view._job_store  # noqa: SLF001
    assert isinstance(store, InMemoryJobStore)

    return store.list_all()[-1]


def test_choosing_9_16_makes_a_vertical_project_rendering_at_1080x1920(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _create(_form_view(), 1)

    assert job.aspect_ratio == AspectRatio.PORTRAIT
    assert job.output_resolution == "1080x1920"


def test_choosing_16_9_leaves_the_project_as_it_always_was(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _create(_form_view(), 0)

    assert job.aspect_ratio == AspectRatio.LANDSCAPE
    assert job.output_resolution == "1920x1080"


# ---------------------------------------------------------------- Render tab


def _resolutions(job: VideoJob) -> list[str]:
    store = InMemoryJobStore()
    store.add(job)
    view = RenderWorkspaceView(
        job_store=store,
        render_runtime_factory=object(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)
    combo = next(c for c in view.findChildren(QComboBox) if c.currentData() is not None)

    assert combo.currentData() == job.output_resolution

    return [combo.itemData(i) for i in range(combo.count())]


def test_the_render_tab_offers_vertical_sizes_for_a_vertical_project(
    qapp: QApplication,  # noqa: F811
) -> None:
    sizes = _resolutions(_job(AspectRatio.PORTRAIT, "1080x1920"))

    assert sizes == ["720x1280", "1080x1920", "1440x2560", "2160x3840"]


def test_the_render_tab_still_offers_landscape_sizes_otherwise(
    qapp: QApplication,  # noqa: F811
) -> None:
    assert _resolutions(_job())[1] == "1920x1080"


# -------------------------------------------------------------- title card size


@pytest.mark.parametrize(
    ("size", "expected"),
    [("1080x1920", (1080, 1920)), ("1920x1080", (1920, 1080)), ("junk", (1920, 1080))],
)
def test_the_title_card_is_made_at_the_renders_own_size(
    size: str, expected: tuple[int, int]
) -> None:
    assert _render_size(_job(size=size)) == expected


# ----------------------------------------------------------- export variants


def _portrait_master() -> VideoJob:
    return _job(AspectRatio.PORTRAIT, "1080x1920")


def test_a_vertical_render_is_its_own_portrait_variant_with_no_ffmpeg_call() -> None:
    service, execution = _service()

    variant = service.build(
        job=_portrait_master(),
        render_result=_render_result(),
        orientation=AspectRatio.PORTRAIT,
    )

    assert variant.output_file == "F:/renders/job1/output.mp4"
    assert execution.calls == []


def test_a_landscape_variant_of_a_vertical_render_fits_it_over_a_blurred_copy() -> None:
    service, execution = _service()

    service.build(
        job=_portrait_master(),
        render_result=_render_result(),
        orientation=AspectRatio.LANDSCAPE,
    )

    command = execution.calls[0][0].filter_complex

    assert "scale=1920:1080:force_original_aspect_ratio=increase" in command
    assert "[fg]scale=-2:1080[fgv]" in command


def test_a_landscape_render_still_makes_its_portrait_variant_as_before() -> None:
    service, execution = _service()

    service.build(
        job=_job(),
        render_result=_render_result(),
        orientation=AspectRatio.PORTRAIT,
    )

    command = execution.calls[0][0].filter_complex

    assert "scale=1080:1920:force_original_aspect_ratio=increase" in command
    assert "[fg]scale=1080:-2[fgv]" in command


def test_the_clause_fits_the_height_only_when_asked() -> None:
    wide, _ = ExportVariantRenderService._reformat_clause(  # noqa: SLF001
        input_label="0:v", width=1920, height=1080, fit_height=True
    )
    tall, _ = ExportVariantRenderService._reformat_clause(  # noqa: SLF001
        input_label="0:v", width=1080, height=1920
    )

    assert "[fg]scale=-2:1080[fgv]" in wide
    assert "[fg]scale=1080:-2[fgv]" in tall
