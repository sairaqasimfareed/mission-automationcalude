from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.models.editing_directives import (
    AnimationDirective,
    CameraDirective,
    DirectiveIntensity,
    DirectiveTimingMode,
    EditingDirectiveStatus,
    MusicDirective,
    SceneEditingDirectives,
    SoundEffectDirective,
    SubtitleDirective,
    TransitionDirective,
    VisualEffectDirective,
)
from src.models.genre_profile import (
    GenreProfile,
)
from src.models.scene import Scene
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)

_INTENSITY_ORDER = [
    DirectiveIntensity.VERY_LOW,
    DirectiveIntensity.LOW,
    DirectiveIntensity.MEDIUM,
    DirectiveIntensity.HIGH,
]

# Scene semantic intent -> directive selection bridge: a scene's
# narrative_function (set only by ScenePlannerAgent.
# plan_from_generated_script) shifts the genre's base effect
# intensity up or down a step, so a CLIMAX scene reads more intense
# and an AFTERSHOCK scene reads calmer than the genre's flat default,
# without a scene-by-scene preset rewrite.
_HIGH_TENSION_BEATS = frozenset({"climax", "major_revelation", "escalation"})
_LOW_TENSION_BEATS = frozenset({"setup", "aftershock"})


class GenreDirectiveGenerationService:
    """
    Generate machine-readable scene editing directives from
    universal genre profiles.

    Priority order:

    1. Scene-specific override
    2. Genre profile default
    3. System model default
    """

    def __init__(
        self,
        *,
        genre_registry: GenreProfileRegistryService,
    ) -> None:
        self.genre_registry = genre_registry

    def generate(
        self,
        *,
        scene: Scene,
        genre_id: str,
        overrides: SceneEditingDirectives | None = None,
    ) -> SceneEditingDirectives:
        """
        Generate editing directives for one scene.

        Unknown or unavailable genres use the registry's safe
        fallback profile.
        """

        resolution = self.genre_registry.resolve(
            genre_id,
            allow_fallback=True,
        )

        if (
            not resolution.is_resolved
            or resolution.profile is None
            or resolution.resolved_genre_id is None
        ):
            raise ValueError("Genre profile could not be resolved: " f"{genre_id}")

        profile = resolution.profile

        directives = self._build_from_profile(
            scene=scene,
            profile=profile,
        )

        if overrides is not None:
            directives = self.apply_overrides(
                base=directives,
                overrides=overrides,
            )

        directives.metadata.update(
            {
                "requested_genre_id": genre_id.strip().lower(),
                "resolved_genre_id": (resolution.resolved_genre_id),
                "genre_fallback_used": (resolution.used_fallback),
                "genre_profile_version": (profile.version),
                "genre_profile_schema_version": (profile.schema_version),
                "scene_title": scene.title,
                "scene_duration_seconds": (scene.estimated_duration_seconds),
            }
        )

        if (
            resolution.warning is not None
            and resolution.warning not in directives.warnings
        ):
            directives.warnings.append(resolution.warning)

        directives.status = EditingDirectiveStatus.DRAFT

        return directives

    def generate_many(
        self,
        *,
        scenes: list[Scene],
        genre_id: str,
        overrides_by_scene: (
            dict[
                int,
                SceneEditingDirectives,
            ]
            | None
        ) = None,
    ) -> list[SceneEditingDirectives]:
        """
        Generate directives for multiple scenes.

        Scene numbers must be unique.
        """

        scene_numbers = [scene.scene_number for scene in scenes]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Duplicate scene numbers cannot be used "
                "for genre directive generation."
            )

        override_map = overrides_by_scene or {}

        unknown_override_scenes = set(override_map) - set(scene_numbers)

        if unknown_override_scenes:
            unknown_text = ", ".join(
                str(scene_number) for scene_number in sorted(unknown_override_scenes)
            )

            raise ValueError(
                "Editing overrides reference unknown " f"scene numbers: {unknown_text}"
            )

        return [
            self.generate(
                scene=scene,
                genre_id=genre_id,
                overrides=override_map.get(scene.scene_number),
            )
            for scene in sorted(
                scenes,
                key=lambda item: item.scene_number,
            )
        ]

    def apply_overrides(
        self,
        *,
        base: SceneEditingDirectives,
        overrides: SceneEditingDirectives,
    ) -> SceneEditingDirectives:
        """
        Merge scene-specific directives over genre defaults.

        Scalar directive groups are replaced by the override.
        Effect collections are merged by preset ID, with override
        values replacing matching genre defaults.
        """

        if base.scene_number != overrides.scene_number:
            raise ValueError(
                "Editing override scene number must match "
                "the generated genre directives."
            )

        merged = base.model_copy(deep=True)

        self._apply_camera_override(
            merged=merged,
            overrides=overrides,
        )

        self._apply_transition_overrides(
            merged=merged,
            overrides=overrides,
        )

        self._apply_music_override(
            merged=merged,
            overrides=overrides,
        )

        self._apply_subtitle_override(
            merged=merged,
            overrides=overrides,
        )

        merged.visual_effects = self._merge_directive_lists(
            base_items=merged.visual_effects,
            override_items=(overrides.visual_effects),
        )

        merged.animations = self._merge_directive_lists(
            base_items=merged.animations,
            override_items=(overrides.animations),
        )

        merged.sound_effects = self._merge_directive_lists(
            base_items=merged.sound_effects,
            override_items=(overrides.sound_effects),
        )

        if overrides.genre_preset_id != "genre.default":
            merged.genre_preset_id = overrides.genre_preset_id

        for warning in overrides.warnings:
            if warning not in merged.warnings:
                merged.warnings.append(warning)

        merged.metadata.update(deepcopy(overrides.metadata))

        merged.metadata["scene_overrides_applied"] = True

        merged.status = EditingDirectiveStatus.DRAFT

        return SceneEditingDirectives.model_validate(merged.model_dump())

    @staticmethod
    def _intensity_for_scene(
        *,
        base_intensity: DirectiveIntensity,
        scene: Scene,
    ) -> DirectiveIntensity:
        """
        Shift the genre's base effect intensity one step for scenes
        with a known high- or low-tension narrative_function (see
        module docstring). Scenes with no narrative_function (the
        legacy sentence-split planner never sets it) are unaffected.
        """

        if scene.narrative_function is None:
            return base_intensity

        position = _INTENSITY_ORDER.index(base_intensity)

        if scene.narrative_function in _HIGH_TENSION_BEATS:
            position = min(position + 1, len(_INTENSITY_ORDER) - 1)
        elif scene.narrative_function in _LOW_TENSION_BEATS:
            position = max(position - 1, 0)

        return _INTENSITY_ORDER[position]

    @classmethod
    def _build_from_profile(
        cls,
        *,
        scene: Scene,
        profile: GenreProfile,
    ) -> SceneEditingDirectives:
        """Build directive objects from one genre profile."""

        duration_seconds = float(scene.estimated_duration_seconds)

        editing = profile.editing
        intensity = cls._intensity_for_scene(
            base_intensity=editing.effect_intensity,
            scene=scene,
        )

        transition_duration = editing.default_transition_duration_seconds

        camera_end = duration_seconds if duration_seconds > 0 else None

        visual_effects = [
            VisualEffectDirective(
                preset_id=preset_id,
                intensity=intensity,
                timing_mode=(DirectiveTimingMode.FULL_SCENE),
            )
            for preset_id in (editing.visual_preset_ids)
        ]

        animations = [
            AnimationDirective(
                preset_id=preset_id,
                intensity=intensity,
                start_offset_seconds=0.0,
                duration_seconds=(duration_seconds if duration_seconds > 0 else None),
            )
            for preset_id in (editing.animation_preset_ids)
        ]

        sound_effects = GenreDirectiveGenerationService._build_sound_effects(
            preset_ids=(editing.sound_effect_preset_ids),
            scene_duration_seconds=(duration_seconds),
            volume_percent=70.0,
        )

        return SceneEditingDirectives(
            scene_number=scene.scene_number,
            genre_preset_id=profile.genre_id,
            camera=CameraDirective(
                preset_id=(editing.camera_preset_id),
                intensity=intensity,
                start_offset_seconds=0.0,
                end_offset_seconds=camera_end,
            ),
            transition_in=TransitionDirective(
                preset_id=(editing.transition_in_preset_id),
                duration_seconds=(
                    transition_duration
                    if (editing.transition_in_preset_id != "transition.cut")
                    else 0.0
                ),
                intensity=(editing.effect_intensity),
            ),
            transition_out=TransitionDirective(
                preset_id=(editing.transition_out_preset_id),
                duration_seconds=(
                    transition_duration
                    if (editing.transition_out_preset_id != "transition.cut")
                    else 0.0
                ),
                intensity=(editing.effect_intensity),
            ),
            visual_effects=visual_effects,
            animations=animations,
            music=MusicDirective(
                preset_id=(editing.music_preset_id),
                intensity=(editing.effect_intensity),
                volume_percent=(editing.default_music_volume_percent),
                duck_under_voice=True,
                enabled=(editing.music_preset_id != "music.none"),
            ),
            sound_effects=sound_effects,
            subtitles=SubtitleDirective(
                preset_id=(editing.subtitle_preset_id),
                animation_preset_id=(editing.subtitle_animation_preset_id),
                enabled=True,
                burn_into_video=True,
            ),
            status=EditingDirectiveStatus.DRAFT,
            metadata={
                "generated_from_genre_profile": True,
                "genre_profile_id": (profile.genre_id),
                "genre_profile_version": (profile.version),
                "maximum_active_effects": (editing.maximum_active_effects),
            },
        )

    @staticmethod
    def _build_sound_effects(
        *,
        preset_ids: list[str],
        scene_duration_seconds: float,
        volume_percent: float,
    ) -> list[SoundEffectDirective]:
        """
        Build evenly distributed default SFX cues.

        These are genre-level suggestions. A later scene-planning
        layer may replace their timing with semantic script cues.
        """

        if not preset_ids:
            return []

        cue_count = len(preset_ids)

        return [
            SoundEffectDirective(
                preset_id=preset_id,
                timing_mode=(DirectiveTimingMode.RELATIVE_PERCENT),
                relative_position_percent=((index + 1) / (cue_count + 1) * 100.0),
                start_offset_seconds=0.0,
                volume_percent=volume_percent,
                enabled=(scene_duration_seconds > 0),
                metadata={
                    "timing_source": ("genre_default_distribution"),
                },
            )
            for index, preset_id in enumerate(preset_ids)
        ]

    @staticmethod
    def _apply_camera_override(
        *,
        merged: SceneEditingDirectives,
        overrides: SceneEditingDirectives,
    ) -> None:
        """Replace camera when it differs from model defaults."""

        if (
            overrides.camera.preset_id != "camera.none"
            or overrides.camera.start_offset_seconds != 0.0
            or overrides.camera.end_offset_seconds is not None
            or overrides.camera.zoom_start is not None
            or overrides.camera.zoom_end is not None
        ):
            merged.camera = overrides.camera.model_copy(deep=True)

    @staticmethod
    def _apply_transition_overrides(
        *,
        merged: SceneEditingDirectives,
        overrides: SceneEditingDirectives,
    ) -> None:
        """Replace non-default transition directives."""

        if (
            overrides.transition_in.preset_id != "transition.cut"
            or overrides.transition_in.duration_seconds != 0.0
        ):
            merged.transition_in = overrides.transition_in.model_copy(deep=True)

        if (
            overrides.transition_out.preset_id != "transition.cut"
            or overrides.transition_out.duration_seconds != 0.0
        ):
            merged.transition_out = overrides.transition_out.model_copy(deep=True)

    @staticmethod
    def _apply_music_override(
        *,
        merged: SceneEditingDirectives,
        overrides: SceneEditingDirectives,
    ) -> None:
        """Replace music when override is non-default."""

        if (
            overrides.music.preset_id != "music.none"
            or overrides.music.enabled is False
            or overrides.music.volume_percent != 25.0
            or overrides.music.fade_in_seconds != 0.0
            or overrides.music.fade_out_seconds != 0.0
        ):
            merged.music = overrides.music.model_copy(deep=True)

    @staticmethod
    def _apply_subtitle_override(
        *,
        merged: SceneEditingDirectives,
        overrides: SceneEditingDirectives,
    ) -> None:
        """Replace subtitles when override is non-default."""

        if (
            overrides.subtitles.preset_id != "subtitle.default"
            or (overrides.subtitles.animation_preset_id is not None)
            or overrides.subtitles.enabled is False
            or overrides.subtitles.burn_into_video is False
            or (overrides.subtitles.maximum_words_per_line != 8)
        ):
            merged.subtitles = overrides.subtitles.model_copy(deep=True)

    @staticmethod
    def _merge_directive_lists(
        *,
        base_items: list[Any],
        override_items: list[Any],
    ) -> list[Any]:
        """
        Merge directive lists by preset ID.

        Override directives replace matching genre defaults and
        new override IDs are appended.
        """

        merged_by_id = {
            item.preset_id: item.model_copy(deep=True) for item in base_items
        }

        ordered_ids = [item.preset_id for item in base_items]

        for item in override_items:
            if item.preset_id not in ordered_ids:
                ordered_ids.append(item.preset_id)

            merged_by_id[item.preset_id] = item.model_copy(deep=True)

        return [merged_by_id[preset_id] for preset_id in ordered_ids]
