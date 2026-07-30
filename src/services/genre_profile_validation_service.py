from __future__ import annotations

from src.models.effect_registry import (
    EffectCategory,
)
from src.models.genre_profile import (
    GenreProfile,
)
from src.models.genre_profile_validation import (
    GenreProfileValidationResult,
    GenreRegistryValidationResult,
    GenreValidationCode,
    GenreValidationIssue,
    GenreValidationSeverity,
    ResolvedGenreEffectReference,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)


class GenreProfileValidationService:
    """
    Validate universal genre profiles against the effect registry.

    Safe effect fallbacks produce warnings. Unresolved references
    or category mismatches prevent production readiness.
    """

    def __init__(
        self,
        *,
        effect_registry: EffectRegistryService,
    ) -> None:
        self.effect_registry = effect_registry

    def validate_profile(
        self,
        profile: GenreProfile,
    ) -> GenreProfileValidationResult:
        """Validate one universal genre profile."""

        errors: list[GenreValidationIssue] = []
        warnings: list[GenreValidationIssue] = []

        resolved_effects: list[
            ResolvedGenreEffectReference
        ] = []

        references = self._collect_references(
            profile
        )

        for (
            field_path,
            preset_id,
            expected_category,
        ) in references:
            resolution = (
                self.effect_registry.resolve(
                    preset_id,
                    allow_fallback=True,
                )
            )

            reference = ResolvedGenreEffectReference(
                field_path=field_path,
                requested_preset_id=preset_id,
                resolved_preset_id=(
                    resolution.resolved_preset_id
                ),
                found_exact_match=(
                    resolution.found_exact_match
                ),
                used_fallback=(
                    resolution.used_fallback
                ),
                is_resolved=(
                    resolution.is_resolved
                ),
            )

            resolved_effects.append(
                reference
            )

            if (
                not resolution.is_resolved
                or resolution.preset is None
            ):
                errors.append(
                    GenreValidationIssue(
                        code=(
                            GenreValidationCode
                            .UNKNOWN_EFFECT_PRESET
                        ),
                        severity=(
                            GenreValidationSeverity.ERROR
                        ),
                        message=(
                            resolution.warning
                            or (
                                "Genre effect preset "
                                "could not be resolved."
                            )
                        ),
                        genre_id=profile.genre_id,
                        field_path=field_path,
                        requested_preset_id=(
                            preset_id
                        ),
                    )
                )

                continue

            if (
                resolution.preset.category
                != expected_category
            ):
                errors.append(
                    GenreValidationIssue(
                        code=(
                            GenreValidationCode
                            .INVALID_EFFECT_CATEGORY
                        ),
                        severity=(
                            GenreValidationSeverity.ERROR
                        ),
                        message=(
                            "Resolved effect preset category "
                            "does not match the genre profile "
                            "field."
                        ),
                        genre_id=profile.genre_id,
                        field_path=field_path,
                        requested_preset_id=(
                            preset_id
                        ),
                        resolved_preset_id=(
                            resolution
                            .resolved_preset_id
                        ),
                        metadata={
                            "expected_category": (
                                expected_category.value
                            ),
                            "resolved_category": (
                                resolution.preset
                                .category.value
                            ),
                        },
                    )
                )

            if resolution.used_fallback:
                warnings.append(
                    GenreValidationIssue(
                        code=(
                            GenreValidationCode
                            .EFFECT_FALLBACK_USED
                        ),
                        severity=(
                            GenreValidationSeverity
                            .WARNING
                        ),
                        message=(
                            resolution.warning
                            or (
                                "A safe effect fallback "
                                "was selected."
                            )
                        ),
                        genre_id=profile.genre_id,
                        field_path=field_path,
                        requested_preset_id=(
                            preset_id
                        ),
                        resolved_preset_id=(
                            resolution
                            .resolved_preset_id
                        ),
                    )
                )

        active_effect_count = (
            self._calculate_active_effect_count(
                profile
            )
        )

        if (
            active_effect_count
            > profile.editing.maximum_active_effects
        ):
            warnings.append(
                GenreValidationIssue(
                    code=(
                        GenreValidationCode
                        .EXCESSIVE_DEFAULT_EFFECTS
                    ),
                    severity=(
                        GenreValidationSeverity.WARNING
                    ),
                    message=(
                        "The genre profile contains more "
                        "default effects than its configured "
                        "maximum."
                    ),
                    genre_id=profile.genre_id,
                    field_path=(
                        "editing.maximum_active_effects"
                    ),
                    metadata={
                        "active_default_effect_count": (
                            active_effect_count
                        ),
                        "maximum_active_effects": (
                            profile.editing
                            .maximum_active_effects
                        ),
                    },
                )
            )

        if not profile.usable:
            errors.append(
                GenreValidationIssue(
                    code=(
                        GenreValidationCode
                        .UNUSABLE_GENRE_PROFILE
                    ),
                    severity=(
                        GenreValidationSeverity.ERROR
                    ),
                    message=(
                        "The genre profile is not active "
                        "and cannot be used in production."
                    ),
                    genre_id=profile.genre_id,
                    metadata={
                        "profile_status": (
                            profile.status.value
                        ),
                    },
                )
            )

        exact_match_count = sum(
            reference.found_exact_match
            for reference in resolved_effects
        )

        fallback_count = sum(
            reference.used_fallback
            for reference in resolved_effects
        )

        unresolved_count = sum(
            not reference.is_resolved
            for reference in resolved_effects
        )

        is_valid = len(errors) == 0

        return GenreProfileValidationResult(
            genre_id=profile.genre_id,
            is_valid=is_valid,
            is_production_ready=(
                is_valid
                and unresolved_count == 0
                and profile.usable
            ),
            errors=errors,
            warnings=warnings,
            resolved_effects=resolved_effects,
            exact_match_count=exact_match_count,
            fallback_count=fallback_count,
            unresolved_count=unresolved_count,
            active_default_effect_count=(
                active_effect_count
            ),
            metadata={
                "schema_version": (
                    profile.schema_version
                ),
                "profile_version": (
                    profile.version
                ),
                "profile_status": (
                    profile.status.value
                ),
            },
        )

    def validate_registry(
        self,
        registry: GenreProfileRegistryService,
    ) -> GenreRegistryValidationResult:
        """Validate every registered genre profile."""

        errors: list[GenreValidationIssue] = []
        warnings: list[GenreValidationIssue] = []

        profiles = registry.list_all()

        if not registry.contains(
            GenreProfileRegistryService
            .DEFAULT_GENRE_ID
        ):
            errors.append(
                GenreValidationIssue(
                    code=(
                        GenreValidationCode
                        .MISSING_DEFAULT_GENRE
                    ),
                    severity=(
                        GenreValidationSeverity.ERROR
                    ),
                    message=(
                        "The genre registry does not contain "
                        "the required default profile."
                    ),
                    genre_id=(
                        GenreProfileRegistryService
                        .DEFAULT_GENRE_ID
                    ),
                )
            )

        profile_results = [
            self.validate_profile(profile)
            for profile in profiles
        ]

        production_ready_count = sum(
            result.is_production_ready
            for result in profile_results
        )

        is_valid = (
            len(errors) == 0
            and all(
                result.is_valid
                for result in profile_results
            )
        )

        return GenreRegistryValidationResult(
            is_valid=is_valid,
            profile_results=profile_results,
            errors=errors,
            warnings=warnings,
            profile_count=len(profiles),
            production_ready_count=(
                production_ready_count
            ),
        )

    @staticmethod
    def _collect_references(
        profile: GenreProfile,
    ) -> list[
        tuple[
            str,
            str,
            EffectCategory,
        ]
    ]:
        """Collect all editing effect references."""

        references: list[
            tuple[
                str,
                str,
                EffectCategory,
            ]
        ] = [
            (
                "editing.camera_preset_id",
                profile.editing.camera_preset_id,
                EffectCategory.CAMERA,
            ),
            (
                (
                    "editing."
                    "transition_in_preset_id"
                ),
                (
                    profile.editing
                    .transition_in_preset_id
                ),
                EffectCategory.TRANSITION,
            ),
            (
                (
                    "editing."
                    "transition_out_preset_id"
                ),
                (
                    profile.editing
                    .transition_out_preset_id
                ),
                EffectCategory.TRANSITION,
            ),
            (
                "editing.music_preset_id",
                profile.editing.music_preset_id,
                EffectCategory.MUSIC,
            ),
            (
                "editing.subtitle_preset_id",
                (
                    profile.editing
                    .subtitle_preset_id
                ),
                EffectCategory.SUBTITLE,
            ),
        ]

        if (
            profile.editing
            .subtitle_animation_preset_id
            is not None
        ):
            references.append(
                (
                    (
                        "editing."
                        "subtitle_animation_preset_id"
                    ),
                    (
                        profile.editing
                        .subtitle_animation_preset_id
                    ),
                    EffectCategory.ANIMATION,
                )
            )

        for index, preset_id in enumerate(
            profile.editing.visual_preset_ids
        ):
            references.append(
                (
                    (
                        "editing.visual_preset_ids"
                        f"[{index}]"
                    ),
                    preset_id,
                    EffectCategory.VISUAL,
                )
            )

        for index, preset_id in enumerate(
            profile.editing
            .animation_preset_ids
        ):
            references.append(
                (
                    (
                        "editing.animation_preset_ids"
                        f"[{index}]"
                    ),
                    preset_id,
                    EffectCategory.ANIMATION,
                )
            )

        for index, preset_id in enumerate(
            profile.editing
            .sound_effect_preset_ids
        ):
            references.append(
                (
                    (
                        "editing."
                        "sound_effect_preset_ids"
                        f"[{index}]"
                    ),
                    preset_id,
                    EffectCategory.SOUND_EFFECT,
                )
            )

        return references

    @staticmethod
    def _calculate_active_effect_count(
        profile: GenreProfile,
    ) -> int:
        """Count optional genre editing effects."""

        return (
            len(
                profile.editing
                .visual_preset_ids
            )
            + len(
                profile.editing
                .animation_preset_ids
            )
            + len(
                profile.editing
                .sound_effect_preset_ids
            )
        )