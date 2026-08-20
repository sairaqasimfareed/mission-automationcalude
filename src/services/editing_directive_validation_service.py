from __future__ import annotations

from src.models.editing_directive_validation import (
    DirectiveValidationCode,
    DirectiveValidationIssue,
    DirectiveValidationSeverity,
    EditingDirectiveValidationResult,
    ResolvedDirectiveReference,
)
from src.models.editing_directives import (
    DirectiveTimingMode,
    EditingDirectiveStatus,
    SceneEditingDirectives,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)


class EditingDirectiveValidationService:
    """
    Validates scene editing directives against the effect registry.

    Registry fallbacks produce warnings rather than fatal errors.
    Unresolved directives prevent the blueprint from being
    considered render-ready.
    """

    def __init__(
        self,
        *,
        effect_registry: EffectRegistryService,
        maximum_active_effects: int = 12,
    ) -> None:
        if maximum_active_effects < 1:
            raise ValueError("Maximum active effects must be at least 1.")

        self.effect_registry = effect_registry
        self.maximum_active_effects = maximum_active_effects

    def validate(
        self,
        directives: SceneEditingDirectives,
        *,
        scene_duration_seconds: float | None = None,
    ) -> EditingDirectiveValidationResult:
        """Validate one complete scene editing blueprint."""

        errors: list[DirectiveValidationIssue] = []
        warnings: list[DirectiveValidationIssue] = []

        resolved_directives: list[ResolvedDirectiveReference] = []

        preset_references = self._collect_preset_references(directives)

        for directive_path, preset_id in preset_references:
            resolution = self.effect_registry.resolve(
                preset_id,
                allow_fallback=True,
            )

            reference = ResolvedDirectiveReference(
                directive_path=directive_path,
                requested_preset_id=preset_id,
                resolved_preset_id=(resolution.resolved_preset_id),
                found_exact_match=(resolution.found_exact_match),
                used_fallback=resolution.used_fallback,
                is_resolved=resolution.is_resolved,
            )

            resolved_directives.append(reference)

            if not resolution.is_resolved:
                errors.append(
                    DirectiveValidationIssue(
                        code=(DirectiveValidationCode.UNKNOWN_PRESET),
                        severity=(DirectiveValidationSeverity.ERROR),
                        message=(
                            resolution.warning
                            or ("Editing directive could " "not be resolved.")
                        ),
                        directive_path=directive_path,
                        requested_preset_id=preset_id,
                    )
                )

                continue

            if resolution.used_fallback:
                warnings.append(
                    DirectiveValidationIssue(
                        code=(DirectiveValidationCode.FALLBACK_USED),
                        severity=(DirectiveValidationSeverity.WARNING),
                        message=(
                            resolution.warning
                            or ("A safe effect fallback " "was used.")
                        ),
                        directive_path=directive_path,
                        requested_preset_id=preset_id,
                        resolved_preset_id=(resolution.resolved_preset_id),
                    )
                )

        self._validate_effect_count(
            directives=directives,
            warnings=warnings,
        )

        if scene_duration_seconds is not None:
            self._validate_scene_timing(
                directives=directives,
                scene_duration_seconds=(scene_duration_seconds),
                errors=errors,
                warnings=warnings,
            )

        exact_match_count = sum(
            reference.found_exact_match for reference in resolved_directives
        )

        fallback_count = sum(
            reference.used_fallback for reference in resolved_directives
        )

        unresolved_count = sum(
            not reference.is_resolved for reference in resolved_directives
        )

        is_valid = len(errors) == 0

        return EditingDirectiveValidationResult(
            scene_number=directives.scene_number,
            is_valid=is_valid,
            is_render_ready=(is_valid and unresolved_count == 0),
            errors=errors,
            warnings=warnings,
            resolved_directives=resolved_directives,
            exact_match_count=exact_match_count,
            fallback_count=fallback_count,
            unresolved_count=unresolved_count,
            metadata={
                "schema_version": (directives.schema_version),
                "genre_preset_id": (directives.genre_preset_id),
                "active_effect_count": (directives.active_effect_count),
            },
        )

    def validate_and_update(
        self,
        directives: SceneEditingDirectives,
        *,
        scene_duration_seconds: float | None = None,
    ) -> EditingDirectiveValidationResult:
        """
        Validate directives and update their lifecycle state.

        Warnings are copied into the directive model without
        introducing duplicates.
        """

        result = self.validate(
            directives,
            scene_duration_seconds=(scene_duration_seconds),
        )

        if result.is_render_ready:
            directives.status = EditingDirectiveStatus.READY
        else:
            directives.status = EditingDirectiveStatus.FAILED

        for issue in result.warnings:
            if issue.message not in directives.warnings:
                directives.warnings.append(issue.message)

        for issue in result.errors:
            if issue.message not in directives.warnings:
                directives.warnings.append(issue.message)

        return result

    @staticmethod
    def _collect_preset_references(
        directives: SceneEditingDirectives,
    ) -> list[tuple[str, str]]:
        """Collect every registered preset reference."""

        references: list[tuple[str, str]] = [
            (
                "genre_preset_id",
                directives.genre_preset_id,
            ),
            (
                "camera.preset_id",
                directives.camera.preset_id,
            ),
            (
                "transition_in.preset_id",
                directives.transition_in.preset_id,
            ),
            (
                "transition_out.preset_id",
                directives.transition_out.preset_id,
            ),
            (
                "music.preset_id",
                directives.music.preset_id,
            ),
            (
                "subtitles.preset_id",
                directives.subtitles.preset_id,
            ),
        ]

        if directives.subtitles.animation_preset_id is not None:
            references.append(
                (
                    ("subtitles." "animation_preset_id"),
                    (directives.subtitles.animation_preset_id),
                )
            )

        for index, visual_effect in enumerate(directives.visual_effects):
            if visual_effect.enabled:
                references.append(
                    (
                        ("visual_effects" f"[{index}].preset_id"),
                        visual_effect.preset_id,
                    )
                )

        for index, animation in enumerate(directives.animations):
            if animation.enabled:
                references.append(
                    (
                        ("animations" f"[{index}].preset_id"),
                        animation.preset_id,
                    )
                )

        for index, sound_effect in enumerate(directives.sound_effects):
            if sound_effect.enabled:
                references.append(
                    (
                        ("sound_effects" f"[{index}].preset_id"),
                        sound_effect.preset_id,
                    )
                )

        return references

    def _validate_effect_count(
        self,
        *,
        directives: SceneEditingDirectives,
        warnings: list[DirectiveValidationIssue],
    ) -> None:
        """Warn when one scene contains too many effects."""

        if directives.active_effect_count <= self.maximum_active_effects:
            return

        warnings.append(
            DirectiveValidationIssue(
                code=(DirectiveValidationCode.EXCESSIVE_EFFECT_COUNT),
                severity=(DirectiveValidationSeverity.WARNING),
                message=(
                    "The scene contains more active "
                    "effects than the configured limit."
                ),
                directive_path="active_effect_count",
                metadata={
                    "active_effect_count": (directives.active_effect_count),
                    "maximum_active_effects": (self.maximum_active_effects),
                },
            )
        )

    def _validate_scene_timing(
        self,
        *,
        directives: SceneEditingDirectives,
        scene_duration_seconds: float,
        errors: list[DirectiveValidationIssue],
        warnings: list[DirectiveValidationIssue],
    ) -> None:
        """Validate directive timing against scene duration."""

        if scene_duration_seconds <= 0:
            errors.append(
                DirectiveValidationIssue(
                    code=(DirectiveValidationCode.INVALID_SCENE_DURATION),
                    severity=(DirectiveValidationSeverity.ERROR),
                    message=(
                        "Scene duration must be positive " "for editing validation."
                    ),
                    directive_path=("scene_duration_seconds"),
                )
            )

            return

        camera_end = directives.camera.end_offset_seconds

        if camera_end is not None and camera_end > scene_duration_seconds:
            errors.append(
                self._outside_scene_issue(
                    directive_path=("camera.end_offset_seconds"),
                    requested_value=camera_end,
                    scene_duration_seconds=(scene_duration_seconds),
                )
            )

        transition_total = (
            directives.transition_in.duration_seconds
            + directives.transition_out.duration_seconds
        )

        if transition_total > scene_duration_seconds:
            errors.append(
                DirectiveValidationIssue(
                    code=(DirectiveValidationCode.TRANSITIONS_EXCEED_SCENE),
                    severity=(DirectiveValidationSeverity.ERROR),
                    message=(
                        "Combined transition duration " "exceeds the scene duration."
                    ),
                    directive_path=("transition_in/transition_out"),
                    metadata={
                        "combined_duration_seconds": (transition_total),
                        "scene_duration_seconds": (scene_duration_seconds),
                    },
                )
            )

        music_fade_total = (
            directives.music.fade_in_seconds + directives.music.fade_out_seconds
        )

        if music_fade_total > scene_duration_seconds:
            warnings.append(
                DirectiveValidationIssue(
                    code=(DirectiveValidationCode.MUSIC_FADES_EXCEED_SCENE),
                    severity=(DirectiveValidationSeverity.WARNING),
                    message=(
                        "Combined music fade duration " "exceeds the scene duration."
                    ),
                    directive_path="music",
                    metadata={
                        "combined_fade_seconds": (music_fade_total),
                        "scene_duration_seconds": (scene_duration_seconds),
                    },
                )
            )

        for index, visual_effect in enumerate(directives.visual_effects):
            if not visual_effect.enabled:
                continue

            if visual_effect.start_offset_seconds > scene_duration_seconds:
                errors.append(
                    self._outside_scene_issue(
                        directive_path=(
                            "visual_effects" f"[{index}]." "start_offset_seconds"
                        ),
                        requested_value=(visual_effect.start_offset_seconds),
                        scene_duration_seconds=(scene_duration_seconds),
                    )
                )

            if (
                visual_effect.duration_seconds is not None
                and (
                    visual_effect.start_offset_seconds + visual_effect.duration_seconds
                )
                > scene_duration_seconds
            ):
                errors.append(
                    self._outside_scene_issue(
                        directive_path=("visual_effects" f"[{index}].duration_seconds"),
                        requested_value=(
                            visual_effect.start_offset_seconds
                            + visual_effect.duration_seconds
                        ),
                        scene_duration_seconds=(scene_duration_seconds),
                    )
                )

        for index, animation in enumerate(directives.animations):
            if not animation.enabled:
                continue

            if animation.start_offset_seconds > scene_duration_seconds:
                errors.append(
                    self._outside_scene_issue(
                        directive_path=(
                            "animations" f"[{index}]." "start_offset_seconds"
                        ),
                        requested_value=(animation.start_offset_seconds),
                        scene_duration_seconds=(scene_duration_seconds),
                    )
                )

            if (
                animation.duration_seconds is not None
                and (animation.start_offset_seconds + animation.duration_seconds)
                > scene_duration_seconds
            ):
                errors.append(
                    self._outside_scene_issue(
                        directive_path=("animations" f"[{index}]." "duration_seconds"),
                        requested_value=(
                            animation.start_offset_seconds + animation.duration_seconds
                        ),
                        scene_duration_seconds=(scene_duration_seconds),
                    )
                )

        for index, sound_effect in enumerate(directives.sound_effects):
            if not sound_effect.enabled:
                continue

            if (
                sound_effect.timing_mode == DirectiveTimingMode.ABSOLUTE_SECONDS
                and sound_effect.start_offset_seconds > scene_duration_seconds
            ):
                errors.append(
                    self._outside_scene_issue(
                        directive_path=(
                            "sound_effects" f"[{index}]." "start_offset_seconds"
                        ),
                        requested_value=(sound_effect.start_offset_seconds),
                        scene_duration_seconds=(scene_duration_seconds),
                    )
                )

    @staticmethod
    def _outside_scene_issue(
        *,
        directive_path: str,
        requested_value: float,
        scene_duration_seconds: float,
    ) -> DirectiveValidationIssue:
        """Build a standard outside-scene validation issue."""

        return DirectiveValidationIssue(
            code=(DirectiveValidationCode.DIRECTIVE_OUTSIDE_SCENE),
            severity=(DirectiveValidationSeverity.ERROR),
            message=("Editing directive timing extends " "outside the scene duration."),
            directive_path=directive_path,
            metadata={
                "requested_end_seconds": requested_value,
                "scene_duration_seconds": (scene_duration_seconds),
            },
        )
