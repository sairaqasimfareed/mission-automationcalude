"""
REQ-12 (top10 countdown rank cards), 2026-09-23: rank_badge_text must
carry through EffectExecutionService.build_scene_effects() from a
resolved ResolvedVisualEffectInstruction onto the final EffectExecution
- the same copy-through this codebase already does for
numeric_intensity_percent (REQ-1/2).
"""

from __future__ import annotations

from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
    ResolvedVisualEffectInstruction,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.effect_execution_service import (
    EffectExecutionService,
)


def _build_reference(*, preset_id: str) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path="visual_effects.preset_id",
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
        implementation={},
        metadata={},
    )


def _build_rank_badge_instruction(
    *,
    rank_badge_text: str | None,
) -> ResolvedVisualEffectInstruction:
    return ResolvedVisualEffectInstruction(
        preset=_build_reference(preset_id="visual.top10_rank_badge"),
        intensity=DirectiveIntensity.MEDIUM,
        rank_badge_text=rank_badge_text,
        timing_mode=DirectiveTimingMode.FULL_SCENE,
        enabled=True,
    )


def _build_item(
    *,
    scene_number: int,
    effects: list[ResolvedVisualEffectInstruction],
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=8,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=(f"assets/videos/manual/scene_{scene_number:03}.mp4"),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    blueprint = ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_build_reference(preset_id="genre.top10"),
        camera=ResolvedCameraInstruction(
            preset=_build_reference(preset_id="camera.none"),
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_build_reference(preset_id="transition.cut"),
            duration_seconds=0.0,
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_build_reference(preset_id="transition.cut"),
            duration_seconds=0.0,
        ),
        visual_effects=effects,
        animations=[],
        music=ResolvedMusicInstruction(
            preset=_build_reference(preset_id="music.none"),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=_build_reference(preset_id="subtitle.default"),
            enabled=False,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        editing_blueprint=blueprint,
    )


def test_rank_badge_text_carries_through_to_the_execution() -> None:
    service = EffectExecutionService()

    item = _build_item(
        scene_number=1,
        effects=[_build_rank_badge_instruction(rank_badge_text="10")],
    )

    executions = service.build_scene_effects(item=item)

    assert len(executions) == 1
    assert executions[0].preset_id == "visual.top10_rank_badge"
    assert executions[0].rank_badge_text == "10"


def test_non_badge_effects_keep_rank_badge_text_as_none() -> None:
    service = EffectExecutionService()

    item = _build_item(
        scene_number=1,
        effects=[_build_rank_badge_instruction(rank_badge_text=None)],
    )

    executions = service.build_scene_effects(item=item)

    assert len(executions) == 1
    assert executions[0].rank_badge_text is None
