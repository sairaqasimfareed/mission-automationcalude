from __future__ import annotations

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedAnimationInstruction,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSoundEffectInstruction,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
    ResolvedVisualEffectInstruction,
)
from src.services.editing_directive_validation_service import (
    EditingDirectiveValidationService,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)


class EditingDirectiveResolutionService:
    """
    Resolve validated editing directives into a normalized
    provider-independent blueprint.

    Unknown or inactive effect IDs use registry fallbacks when
    available. Unresolved references prevent blueprint creation.
    """

    def __init__(
        self,
        *,
        effect_registry: EffectRegistryService,
        validation_service: EditingDirectiveValidationService | None = None,
    ) -> None:
        self.effect_registry = effect_registry

        self.validation_service = (
            validation_service
            or EditingDirectiveValidationService(
                effect_registry=effect_registry,
            )
        )

    def resolve(
        self,
        directives: SceneEditingDirectives,
        *,
        scene_duration_seconds: float | None = None,
    ) -> ResolvedSceneEditingBlueprint:
        """Resolve one scene directive collection."""

        validation_result = self.validation_service.validate(
            directives,
            scene_duration_seconds=(scene_duration_seconds),
        )

        if not validation_result.is_render_ready:
            error_messages = [issue.message for issue in validation_result.errors]

            raise ValueError(
                "Editing directives cannot be resolved: " + "; ".join(error_messages)
            )

        warnings = [issue.message for issue in validation_result.warnings]

        genre_preset = self._resolve_reference(
            directive_path="genre_preset_id",
            preset_id=directives.genre_preset_id,
        )

        camera_preset = self._resolve_reference(
            directive_path="camera.preset_id",
            preset_id=directives.camera.preset_id,
        )

        transition_in_preset = self._resolve_reference(
            directive_path=("transition_in.preset_id"),
            preset_id=(directives.transition_in.preset_id),
        )

        transition_out_preset = self._resolve_reference(
            directive_path=("transition_out.preset_id"),
            preset_id=(directives.transition_out.preset_id),
        )

        music_preset = self._resolve_reference(
            directive_path="music.preset_id",
            preset_id=directives.music.preset_id,
        )

        subtitle_preset = self._resolve_reference(
            directive_path="subtitles.preset_id",
            preset_id=directives.subtitles.preset_id,
        )

        subtitle_animation_preset = None

        if directives.subtitles.animation_preset_id is not None:
            subtitle_animation_preset = self._resolve_reference(
                directive_path=("subtitles." "animation_preset_id"),
                preset_id=(directives.subtitles.animation_preset_id),
            )

        visual_effects = [
            ResolvedVisualEffectInstruction(
                preset=self._resolve_reference(
                    directive_path=("visual_effects" f"[{index}].preset_id"),
                    preset_id=effect.preset_id,
                ),
                intensity=effect.intensity,
                timing_mode=effect.timing_mode,
                start_offset_seconds=(effect.start_offset_seconds),
                duration_seconds=(effect.duration_seconds),
                relative_position_percent=(effect.relative_position_percent),
                enabled=effect.enabled,
            )
            for index, effect in enumerate(directives.visual_effects)
            if effect.enabled
        ]

        animations = [
            ResolvedAnimationInstruction(
                preset=self._resolve_reference(
                    directive_path=("animations" f"[{index}].preset_id"),
                    preset_id=animation.preset_id,
                ),
                intensity=animation.intensity,
                start_offset_seconds=(animation.start_offset_seconds),
                duration_seconds=(animation.duration_seconds),
                enabled=animation.enabled,
            )
            for index, animation in enumerate(directives.animations)
            if animation.enabled
        ]

        sound_effects = [
            ResolvedSoundEffectInstruction(
                preset=self._resolve_reference(
                    directive_path=("sound_effects" f"[{index}].preset_id"),
                    preset_id=sound_effect.preset_id,
                ),
                timing_mode=sound_effect.timing_mode,
                start_offset_seconds=(sound_effect.start_offset_seconds),
                relative_position_percent=(sound_effect.relative_position_percent),
                volume_percent=(sound_effect.volume_percent),
                intensity=sound_effect.intensity,
                enabled=sound_effect.enabled,
            )
            for index, sound_effect in enumerate(directives.sound_effects)
            if sound_effect.enabled
        ]

        status = (
            BlueprintResolutionStatus.RESOLVED_WITH_FALLBACKS
            if validation_result.fallback_count > 0
            else BlueprintResolutionStatus.RESOLVED
        )

        blueprint = ResolvedSceneEditingBlueprint(
            scene_number=directives.scene_number,
            genre_preset=genre_preset,
            camera=ResolvedCameraInstruction(
                preset=camera_preset,
                intensity=directives.camera.intensity,
                start_offset_seconds=(directives.camera.start_offset_seconds),
                end_offset_seconds=(directives.camera.end_offset_seconds),
                zoom_start=(directives.camera.zoom_start),
                zoom_end=directives.camera.zoom_end,
            ),
            transition_in=(
                ResolvedTransitionInstruction(
                    preset=transition_in_preset,
                    duration_seconds=(directives.transition_in.duration_seconds),
                    intensity=(directives.transition_in.intensity),
                )
            ),
            transition_out=(
                ResolvedTransitionInstruction(
                    preset=transition_out_preset,
                    duration_seconds=(directives.transition_out.duration_seconds),
                    intensity=(directives.transition_out.intensity),
                )
            ),
            visual_effects=visual_effects,
            animations=animations,
            music=ResolvedMusicInstruction(
                preset=music_preset,
                intensity=directives.music.intensity,
                volume_percent=(directives.music.volume_percent),
                fade_in_seconds=(directives.music.fade_in_seconds),
                fade_out_seconds=(directives.music.fade_out_seconds),
                duck_under_voice=(directives.music.duck_under_voice),
                enabled=directives.music.enabled,
            ),
            sound_effects=sound_effects,
            subtitles=ResolvedSubtitleInstruction(
                preset=subtitle_preset,
                animation_preset=(subtitle_animation_preset),
                enabled=directives.subtitles.enabled,
                burn_into_video=(directives.subtitles.burn_into_video),
                maximum_words_per_line=(directives.subtitles.maximum_words_per_line),
            ),
            status=status,
            fallback_count=(validation_result.fallback_count),
            exact_match_count=(validation_result.exact_match_count),
            warnings=warnings,
            metadata={
                "source_schema_version": (directives.schema_version),
                "validation_issue_count": (validation_result.issue_count),
                "active_effect_count": (directives.active_effect_count),
            },
        )

        return blueprint

    def _resolve_reference(
        self,
        *,
        directive_path: str,
        preset_id: str,
    ) -> ResolvedPresetReference:
        """Resolve one registry reference."""

        resolution = self.effect_registry.resolve(
            preset_id,
            allow_fallback=True,
        )

        if (
            not resolution.is_resolved
            or resolution.preset is None
            or resolution.resolved_preset_id is None
        ):
            raise ValueError("Effect preset could not be resolved: " f"{preset_id}")

        return ResolvedPresetReference(
            directive_path=directive_path,
            requested_preset_id=preset_id,
            resolved_preset_id=(resolution.resolved_preset_id),
            found_exact_match=(resolution.found_exact_match),
            used_fallback=(resolution.used_fallback),
            implementation=dict(resolution.preset.implementation),
            metadata={
                "display_name": (resolution.preset.display_name),
                "version": (resolution.preset.version),
                "category": (resolution.preset.category.value),
            },
        )
