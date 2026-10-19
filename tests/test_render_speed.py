"""
Render speed (2026-10-19). Measured on the app's own render chain (Joan arc, an i7-5600U laptop): the film-grain
filter (`noise ... allf=t`) cost about 93 CPU-seconds per second of video, six to seven times the cost of encoding
the picture itself, so a render of an 88 s video ran at 0.02x speed. The Render tab now offers Final (the full look,
exactly as before), Balanced and Draft: the two faster modes leave the film grain out of the render copy of the
timeline and encode with a faster x264 preset. Nothing else about the video changes.
"""

from __future__ import annotations

from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_speed import RenderSpeed
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.production_render_service import ProductionRenderService
from src.services.render_speed_rules import (
    FILM_GRAIN_PRESET_ID,
    timeline_for_render_speed,
)
from tests.test_render_stage import build_job

_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _timeline(genre_id: str):  # type: ignore[no-untyped-def]
    scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt="v",
            estimated_duration_seconds=4,
            status=SceneStatus.READY,
        )
        for n in (1, 2)
    ]
    clips = [
        VideoClip(
            scene_number=n,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=4,
            local_file=f"clips/{n}.mp4",
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )
        for n in (1, 2)
    ]

    return (
        GenreTimelinePipelineService(
            genre_directive_service=GenreDirectiveGenerationService(
                genre_registry=_REGISTRY
            ),
            directive_resolution_service=EditingDirectiveResolutionService(
                effect_registry=EffectRegistryService.with_default_presets()
            ),
        )
        .build(scenes=scenes, clips=clips, genre_id=genre_id)
        .timeline
    )


def _effect_ids(timeline) -> list[list[str]]:  # type: ignore[no-untyped-def]
    return [
        [e.preset.resolved_preset_id for e in item.editing_blueprint.visual_effects]
        for item in timeline.items
        if item.editing_blueprint is not None
    ]


def test_a_project_renders_at_full_quality_unless_told_otherwise() -> None:
    assert build_job().render_speed == RenderSpeed.FINAL


def test_each_speed_has_its_own_encoder_preset_and_grain_rule() -> None:
    assert RenderSpeed.FINAL.x264_preset == "medium" and RenderSpeed.FINAL.film_grain
    assert (
        RenderSpeed.BALANCED.x264_preset == "fast"
        and not RenderSpeed.BALANCED.film_grain
    )
    assert (
        RenderSpeed.DRAFT.x264_preset == "veryfast" and not RenderSpeed.DRAFT.film_grain
    )


def test_a_final_render_uses_the_timeline_itself() -> None:
    timeline = _timeline("genre.mystery")
    job = build_job()

    assert timeline_for_render_speed(job, timeline) is timeline


def test_a_faster_render_leaves_out_only_the_film_grain_and_keeps_the_stored_timeline() -> (
    None
):
    timeline = _timeline("genre.mystery")
    before = _effect_ids(timeline)
    assert any(
        FILM_GRAIN_PRESET_ID in ids for ids in before
    ), "the genre has film grain"

    job = build_job()
    job.render_speed = RenderSpeed.DRAFT
    render_copy = timeline_for_render_speed(job, timeline)
    after = _effect_ids(render_copy)

    assert all(FILM_GRAIN_PRESET_ID not in ids for ids in after)
    assert [[i for i in ids if i != FILM_GRAIN_PRESET_ID] for ids in before] == after
    assert _effect_ids(timeline) == before  # the stored timeline still has its grain
    assert render_copy is not timeline


def test_the_render_service_uses_the_chosen_preset_and_goes_back() -> None:
    service = ProductionRenderService()
    configured = service.ffmpeg_config.preset

    assert service._config_for_render().preset == configured  # noqa: SLF001

    service.set_render_preset("veryfast")
    assert service._config_for_render().preset == "veryfast"  # noqa: SLF001
    assert service.ffmpeg_config.preset == configured  # the configured one is untouched

    service.set_render_preset(None)
    assert service._config_for_render().preset == configured  # noqa: SLF001


def test_the_render_tab_offers_the_three_speeds_and_saves_the_choice() -> None:
    from PySide6.QtWidgets import QApplication, QComboBox

    from src.desktop.job_store import InMemoryJobStore
    from src.desktop.views.render_workspace_view import RenderWorkspaceView
    from tests.test_render_workspace_view_output_resolution import (
        _FakeRenderRuntimeFactory,
        _job,
    )

    _app = QApplication.instance() or QApplication([])
    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = RenderWorkspaceView(
        job_store=store,
        render_runtime_factory=_FakeRenderRuntimeFactory(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)
    speed_combo = next(
        c for c in view.findChildren(QComboBox) if c.itemData(0) == RenderSpeed.FINAL
    )

    assert [speed_combo.itemData(i) for i in range(3)] == list(RenderSpeed)

    speed_combo.setCurrentIndex(2)

    assert job.render_speed == RenderSpeed.DRAFT
