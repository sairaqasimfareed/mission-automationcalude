from __future__ import annotations

from typing import cast

import pytest

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.pipeline.asset_stage import (
    AssetPipelineStage,
)
from src.pipeline.music_stage import MusicPipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)
from src.pipeline.render_stage import (
    RenderPipelineStage,
)
from src.pipeline.sound_effect_stage import SoundEffectPipelineStage
from src.pipeline.timeline_stage import (
    TimelinePipelineStage,
)
from src.pipeline.voice_stage import (
    VoicePipelineStage,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.music_generation_service import MusicGenerationService
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.render_service import (
    RenderService,
)
from src.services.render_workflow_stage_factory import (
    RenderWorkflowStageFactory,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


def _dependency[T](
    dependency_type: type[T],
) -> T:
    """
    Create a typed identity-only dependency.

    These tests verify composition rather than service behavior.
    Dependencies that are only stored by stage constructors do not
    need to be executable.
    """

    del dependency_type

    return cast(
        T,
        object(),
    )


def _blueprint(
    *,
    scene_number: int = 1,
    narration_text: str = "Test narration.",
) -> ResolvedVoiceBlueprint:
    """
    Build one valid resolved voice blueprint.

    A real domain model is used because VoicePipelineStage validates
    blueprint scene mappings during construction.
    """

    return ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=(VoiceBlueprintResolutionStatus.RESOLVED),
        profile=ResolvedVoiceProfileReference(
            requested_profile_id=("voice.test_narrator"),
            resolved_profile_id=("voice.test_narrator"),
            display_name="Test Narrator",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text=narration_text,
    )


def _factory(
    *,
    render_service: RenderService | None = None,
    production_render_service: ProductionRenderService | None = None,
) -> RenderWorkflowStageFactory:
    """
    Build the render workflow factory with typed identity dependencies.

    A caller may explicitly choose either the legacy dry-run renderer
    or the production renderer. Supplying neither exercises the normal
    production-default composition.
    """

    return RenderWorkflowStageFactory(
        voice_generation_service=_dependency(VoiceGenerationService),
        voice_timeline_service=_dependency(VoiceTimelineService),
        asset_workflow_service=_dependency(SceneAssetWorkflowService),
        genre_timeline_service=_dependency(GenreTimelinePipelineService),
        render_service=render_service,
        production_render_service=(production_render_service),
    )


def test_factory_preserves_injected_dependencies() -> None:
    voice_generation_service = _dependency(VoiceGenerationService)

    voice_timeline_service = _dependency(VoiceTimelineService)

    asset_workflow_service = _dependency(SceneAssetWorkflowService)

    genre_timeline_service = _dependency(GenreTimelinePipelineService)

    render_service = _dependency(RenderService)

    factory = RenderWorkflowStageFactory(
        voice_generation_service=(voice_generation_service),
        voice_timeline_service=(voice_timeline_service),
        asset_workflow_service=(asset_workflow_service),
        genre_timeline_service=(genre_timeline_service),
        render_service=render_service,
    )

    assert factory.voice_generation_service is voice_generation_service

    assert factory.voice_timeline_service is voice_timeline_service

    assert factory.asset_workflow_service is asset_workflow_service

    assert factory.genre_timeline_service is genre_timeline_service

    assert factory.render_service is render_service

    assert factory.production_render_service is None

    assert factory.production_render_enabled is False


def test_factory_enables_production_render_by_default() -> None:
    factory = _factory()

    assert factory.production_render_enabled is True

    assert factory.production_render_service is not None

    assert isinstance(
        factory.production_render_service,
        ProductionRenderService,
    )

    assert factory.render_service is None


def test_factory_preserves_explicit_legacy_renderer() -> None:
    legacy_render_service = RenderService()

    factory = _factory(
        render_service=legacy_render_service,
    )

    assert factory.production_render_enabled is False

    assert factory.production_render_service is None

    assert factory.render_service is legacy_render_service


def test_factory_preserves_explicit_production_renderer() -> None:
    production_render_service = ProductionRenderService()

    factory = _factory(
        production_render_service=(production_render_service),
    )

    assert factory.production_render_enabled is True

    assert factory.production_render_service is production_render_service

    assert factory.render_service is None


def test_factory_rejects_two_render_engines() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "Render workflow stage factory cannot "
            "configure both legacy and production "
            "render services"
        ),
    ):
        _factory(
            render_service=RenderService(),
            production_render_service=(ProductionRenderService()),
        )


def test_build_returns_required_stage_order() -> None:
    factory = _factory()

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="documentary",
    )

    assert len(stages) == 4

    assert isinstance(
        stages[0],
        VoicePipelineStage,
    )

    assert isinstance(
        stages[1],
        AssetPipelineStage,
    )

    assert isinstance(
        stages[2],
        TimelinePipelineStage,
    )

    assert isinstance(
        stages[3],
        RenderPipelineStage,
    )

    assert [stage.stage_name for stage in stages] == [
        PipelineStageName.VOICE,
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]


def test_build_inserts_music_and_sound_effect_stages_when_configured() -> None:
    factory = RenderWorkflowStageFactory(
        voice_generation_service=_dependency(VoiceGenerationService),
        voice_timeline_service=_dependency(VoiceTimelineService),
        asset_workflow_service=_dependency(SceneAssetWorkflowService),
        genre_timeline_service=_dependency(GenreTimelinePipelineService),
        music_generation_service=_dependency(MusicGenerationService),
        sound_effect_generation_service=_dependency(SoundEffectGenerationService),
    )

    stages = factory.build(
        voice_blueprints=[_blueprint()],
        genre_id="documentary",
    )

    assert [stage.stage_name for stage in stages] == [
        PipelineStageName.VOICE,
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.BACKGROUND_MUSIC,
        PipelineStageName.SOUND_EFFECTS,
        PipelineStageName.RENDER,
    ]

    assert isinstance(stages[3], MusicPipelineStage)
    assert isinstance(stages[4], SoundEffectPipelineStage)


def test_build_creates_fresh_stage_instances() -> None:
    factory = _factory()

    blueprints = [
        _blueprint(),
    ]

    first = factory.build(
        voice_blueprints=blueprints,
        genre_id="documentary",
    )

    second = factory.build(
        voice_blueprints=blueprints,
        genre_id="documentary",
    )

    assert len(first) == len(second)

    for first_stage, second_stage in zip(
        first,
        second,
        strict=True,
    ):
        assert first_stage is not second_stage


def test_build_preserves_job_specific_voice_blueprints() -> None:
    factory = _factory()

    first_blueprint = _blueprint(
        scene_number=1,
        narration_text=("First scene narration."),
    )

    second_blueprint = _blueprint(
        scene_number=2,
        narration_text=("Second scene narration."),
    )

    stages = factory.build(
        voice_blueprints=[
            first_blueprint,
            second_blueprint,
        ],
        genre_id="documentary",
    )

    voice_stage = cast(
        VoicePipelineStage,
        stages[0],
    )

    assert voice_stage._blueprints == [
        first_blueprint,
        second_blueprint,
    ]


def test_build_passes_voice_blueprints_to_production_render_stage() -> None:
    factory = _factory()

    first_blueprint = _blueprint(
        scene_number=1,
    )

    second_blueprint = _blueprint(
        scene_number=2,
    )

    blueprints = [
        first_blueprint,
        second_blueprint,
    ]

    stages = factory.build(
        voice_blueprints=blueprints,
        genre_id="documentary",
    )

    render_stage = cast(
        RenderPipelineStage,
        stages[3],
    )

    assert render_stage.production_render_enabled is True

    assert render_stage._voice_blueprints == blueprints

    assert render_stage._voice_blueprints is not blueprints


def test_build_forwards_voice_provider_name() -> None:
    factory = _factory()

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="documentary",
        voice_provider_name=("  elevenlabs  "),
    )

    voice_stage = cast(
        VoicePipelineStage,
        stages[0],
    )

    assert voice_stage._provider_name == "elevenlabs"


def test_build_forwards_timeline_configuration() -> None:
    factory = _factory()

    overrides = cast(
        dict[
            int,
            SceneEditingDirectives,
        ],
        {
            1: _dependency(SceneEditingDirectives),
        },
    )

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="  Documentary  ",
        overrides_by_scene=overrides,
        output_resolution="3840x2160",
        frame_rate=60,
        warn_on_blueprint_fallbacks=False,
    )

    timeline_stage = cast(
        TimelinePipelineStage,
        stages[2],
    )

    assert timeline_stage.genre_id == "documentary"

    assert timeline_stage._overrides_by_scene == overrides

    assert timeline_stage._output_resolution == "3840x2160"

    assert timeline_stage._frame_rate == 60

    assert timeline_stage._warn_on_blueprint_fallbacks is False


def test_build_copies_timeline_overrides() -> None:
    factory = _factory()

    overrides = cast(
        dict[
            int,
            SceneEditingDirectives,
        ],
        {
            1: _dependency(SceneEditingDirectives),
        },
    )

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="documentary",
        overrides_by_scene=overrides,
    )

    timeline_stage = cast(
        TimelinePipelineStage,
        stages[2],
    )

    assert timeline_stage._overrides_by_scene == overrides

    assert timeline_stage._overrides_by_scene is not overrides


def test_build_uses_injected_legacy_render_service() -> None:
    render_service = _dependency(RenderService)

    factory = _factory(
        render_service=render_service,
    )

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="documentary",
    )

    render_stage = cast(
        RenderPipelineStage,
        stages[3],
    )

    assert render_stage._render_service is render_service

    assert render_stage.production_render_enabled is False

    assert render_stage._voice_blueprints == []


def test_build_uses_production_renderer_by_default() -> None:
    factory = _factory()

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="documentary",
    )

    render_stage = cast(
        RenderPipelineStage,
        stages[3],
    )

    assert render_stage.production_render_enabled is True

    assert render_stage._production_render_service is factory.production_render_service


def test_build_uses_explicit_production_renderer() -> None:
    production_render_service = ProductionRenderService()

    factory = _factory(
        production_render_service=(production_render_service),
    )

    stages = factory.build(
        voice_blueprints=[
            _blueprint(),
        ],
        genre_id="documentary",
    )

    render_stage = cast(
        RenderPipelineStage,
        stages[3],
    )

    assert render_stage.production_render_enabled is True

    assert render_stage._production_render_service is production_render_service


def test_build_rejects_empty_voice_blueprints() -> None:
    factory = _factory()

    with pytest.raises(
        ValueError,
        match=(
            "Voice pipeline stage requires " "at least one resolved voice blueprint"
        ),
    ):
        factory.build(
            voice_blueprints=[],
            genre_id="documentary",
        )


def test_build_rejects_duplicate_voice_scene_numbers() -> None:
    factory = _factory()

    with pytest.raises(
        ValueError,
    ):
        factory.build(
            voice_blueprints=[
                _blueprint(
                    scene_number=1,
                    narration_text=("First narration."),
                ),
                _blueprint(
                    scene_number=1,
                    narration_text=("Duplicate scene narration."),
                ),
            ],
            genre_id="documentary",
        )


@pytest.mark.parametrize(
    "genre_id",
    [
        "",
        " ",
        "\t",
        "\n",
    ],
)
def test_build_rejects_blank_genre_id(
    genre_id: str,
) -> None:
    factory = _factory()

    with pytest.raises(
        ValueError,
        match=("Timeline pipeline stage requires " "a genre ID"),
    ):
        factory.build(
            voice_blueprints=[
                _blueprint(),
            ],
            genre_id=genre_id,
        )


@pytest.mark.parametrize(
    "frame_rate",
    [
        0,
        -1,
        -30,
    ],
)
def test_build_rejects_non_positive_frame_rate(
    frame_rate: int,
) -> None:
    factory = _factory()

    with pytest.raises(
        ValueError,
        match=("Timeline pipeline stage frame rate " "must be positive"),
    ):
        factory.build(
            voice_blueprints=[
                _blueprint(),
            ],
            genre_id="documentary",
            frame_rate=frame_rate,
        )


@pytest.mark.parametrize(
    "output_resolution",
    [
        "",
        " ",
        "\t",
        "\n",
    ],
)
def test_build_rejects_blank_output_resolution(
    output_resolution: str,
) -> None:
    factory = _factory()

    with pytest.raises(
        ValueError,
        match=("Timeline pipeline stage requires " "an output resolution"),
    ):
        factory.build(
            voice_blueprints=[
                _blueprint(),
            ],
            genre_id="documentary",
            output_resolution=(output_resolution),
        )
