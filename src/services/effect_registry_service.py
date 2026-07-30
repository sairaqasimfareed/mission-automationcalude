from __future__ import annotations

from src.models.effect_registry import (
    EffectCategory,
    EffectPreset,
    EffectPresetStatus,
    EffectResolutionResult,
    normalize_effect_id,
)


class EffectRegistryService:
    """
    Stores and resolves provider-independent effect presets.

    Unknown or disabled presets may resolve to safe category
    fallbacks without crashing the editing workflow.
    """

    DEFAULT_FALLBACK_IDS = {
        EffectCategory.CAMERA: "camera.none",
        EffectCategory.TRANSITION: (
            "transition.cut"
        ),
        EffectCategory.VISUAL: "visual.none",
        EffectCategory.ANIMATION: (
            "animation.none"
        ),
        EffectCategory.MUSIC: "music.none",
        EffectCategory.SOUND_EFFECT: "sfx.none",
        EffectCategory.SUBTITLE: (
            "subtitle.default"
        ),
        EffectCategory.GENRE: "genre.default",
    }

    def __init__(
        self,
        presets: list[EffectPreset] | None = None,
    ) -> None:
        self._presets: dict[
            str,
            EffectPreset,
        ] = {}

        for preset in presets or []:
            self.register(preset)

    def register(
        self,
        preset: EffectPreset,
        *,
        replace: bool = False,
    ) -> None:
        """Register one effect preset."""

        existing = self._presets.get(
            preset.preset_id
        )

        if (
            existing is not None
            and not replace
        ):
            raise ValueError(
                "Effect preset is already registered: "
                f"{preset.preset_id}"
            )

        self._presets[preset.preset_id] = preset

    def unregister(
        self,
        preset_id: str,
    ) -> EffectPreset:
        """Remove and return one registered preset."""

        normalized_id = normalize_effect_id(
            preset_id
        )

        if normalized_id not in self._presets:
            raise KeyError(
                "Effect preset is not registered: "
                f"{normalized_id}"
            )

        return self._presets.pop(
            normalized_id
        )

    def get(
        self,
        preset_id: str,
    ) -> EffectPreset:
        """Return one registered preset."""

        normalized_id = normalize_effect_id(
            preset_id
        )

        if normalized_id not in self._presets:
            raise KeyError(
                "Effect preset is not registered: "
                f"{normalized_id}"
            )

        return self._presets[normalized_id]

    def contains(
        self,
        preset_id: str,
    ) -> bool:
        """Return whether one preset is registered."""

        normalized_id = normalize_effect_id(
            preset_id
        )

        return normalized_id in self._presets

    def list_all(
        self,
        *,
        active_only: bool = False,
    ) -> list[EffectPreset]:
        """Return all registered presets."""

        presets = list(
            self._presets.values()
        )

        if active_only:
            presets = [
                preset
                for preset in presets
                if preset.usable
            ]

        return sorted(
            presets,
            key=lambda preset: (
                preset.category.value,
                preset.display_name.lower(),
                preset.preset_id,
            ),
        )

    def list_by_category(
        self,
        category: EffectCategory,
        *,
        active_only: bool = False,
    ) -> list[EffectPreset]:
        """Return presets from one category."""

        return [
            preset
            for preset in self.list_all(
                active_only=active_only,
            )
            if preset.category == category
        ]

    def resolve(
        self,
        preset_id: str,
        *,
        allow_fallback: bool = True,
    ) -> EffectResolutionResult:
        """
        Resolve one effect ID.

        Exact active matches are preferred. Unknown, disabled,
        or deprecated presets may use a safe category fallback.
        """

        normalized_id = normalize_effect_id(
            preset_id
        )

        exact_preset = self._presets.get(
            normalized_id
        )

        if (
            exact_preset is not None
            and exact_preset.usable
        ):
            return EffectResolutionResult(
                requested_preset_id=normalized_id,
                resolved_preset_id=(
                    exact_preset.preset_id
                ),
                preset=exact_preset,
                found_exact_match=True,
                used_fallback=False,
            )

        if not allow_fallback:
            return EffectResolutionResult(
                requested_preset_id=normalized_id,
                warning=self._build_unresolved_warning(
                    requested_id=normalized_id,
                    preset=exact_preset,
                ),
            )

        fallback_id = self._determine_fallback_id(
            requested_id=normalized_id,
            preset=exact_preset,
        )

        fallback_preset = self._presets.get(
            fallback_id
        )

        if (
            fallback_preset is None
            or not fallback_preset.usable
        ):
            return EffectResolutionResult(
                requested_preset_id=normalized_id,
                warning=(
                    self._build_unresolved_warning(
                        requested_id=normalized_id,
                        preset=exact_preset,
                    )
                    + " No usable fallback preset "
                    "is registered."
                ),
            )

        return EffectResolutionResult(
            requested_preset_id=normalized_id,
            resolved_preset_id=(
                fallback_preset.preset_id
            ),
            preset=fallback_preset,
            found_exact_match=False,
            used_fallback=True,
            warning=(
                self._build_unresolved_warning(
                    requested_id=normalized_id,
                    preset=exact_preset,
                )
                + " Safe fallback "
                f"'{fallback_preset.preset_id}' "
                "was selected."
            ),
        )

    def resolve_many(
        self,
        preset_ids: list[str],
        *,
        allow_fallback: bool = True,
    ) -> list[EffectResolutionResult]:
        """Resolve multiple IDs while preserving order."""

        return [
            self.resolve(
                preset_id,
                allow_fallback=allow_fallback,
            )
            for preset_id in preset_ids
        ]

    def _determine_fallback_id(
        self,
        *,
        requested_id: str,
        preset: EffectPreset | None,
    ) -> str:
        """Return the explicit or category default fallback."""

        if (
            preset is not None
            and preset.fallback_preset_id
            is not None
        ):
            return preset.fallback_preset_id

        category = self._category_from_id(
            requested_id
        )

        return self.DEFAULT_FALLBACK_IDS[
            category
        ]

    @staticmethod
    def _category_from_id(
        preset_id: str,
    ) -> EffectCategory:
        """Extract a category from a normalized ID."""

        prefix = preset_id.split(
            ".",
            maxsplit=1,
        )[0]

        return EffectCategory(prefix)

    @staticmethod
    def _build_unresolved_warning(
        *,
        requested_id: str,
        preset: EffectPreset | None,
    ) -> str:
        """Build a human-readable resolution warning."""

        if preset is None:
            return (
                "Requested effect preset is not "
                f"registered: {requested_id}."
            )

        if (
            preset.status
            == EffectPresetStatus.DISABLED
        ):
            return (
                "Requested effect preset is disabled: "
                f"{requested_id}."
            )

        return (
            "Requested effect preset is not active: "
            f"{requested_id}."
        )

    @classmethod
    def with_default_presets(
        cls,
    ) -> EffectRegistryService:
        """Create a registry with safe foundation presets."""

        return cls(
            presets=cls._build_default_presets()
        )

    @staticmethod
    def _build_default_presets(
    ) -> list[EffectPreset]:
        """Return the initial built-in preset library."""

        return [
            EffectPreset(
                preset_id="camera.none",
                category=EffectCategory.CAMERA,
                display_name="No Camera Motion",
                implementation={
                    "motion": "none",
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id="camera.slow_zoom_in",
                category=EffectCategory.CAMERA,
                display_name="Slow Zoom In",
                fallback_preset_id="camera.none",
                implementation={
                    "motion": "zoom",
                    "direction": "in",
                    "default_start_scale": 1.0,
                    "default_end_scale": 1.08,
                },
                tags=[
                    "cinematic",
                    "documentary",
                    "horror",
                ],
            ),
            EffectPreset(
                preset_id="transition.cut",
                category=(
                    EffectCategory.TRANSITION
                ),
                display_name="Standard Cut",
                implementation={
                    "type": "cut",
                    "default_duration_seconds": 0.0,
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "transition.fade_black"
                ),
                category=(
                    EffectCategory.TRANSITION
                ),
                display_name="Fade Through Black",
                fallback_preset_id=(
                    "transition.cut"
                ),
                implementation={
                    "type": "fade_black",
                    "default_duration_seconds": 0.8,
                },
                tags=[
                    "cinematic",
                    "horror",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "transition.cross_dissolve"
                ),
                category=(
                    EffectCategory.TRANSITION
                ),
                display_name="Cross Dissolve",
                fallback_preset_id=(
                    "transition.cut"
                ),
                implementation={
                    "type": "cross_dissolve",
                    "default_duration_seconds": 0.6,
                },
                tags=[
                    "documentary",
                    "storytelling",
                ],
            ),
            EffectPreset(
                preset_id="visual.none",
                category=EffectCategory.VISUAL,
                display_name="No Visual Effect",
                implementation={
                    "filters": [],
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "visual.horror_dark_grade"
                ),
                category=EffectCategory.VISUAL,
                display_name="Horror Dark Grade",
                fallback_preset_id="visual.none",
                implementation={
                    "brightness": -0.08,
                    "contrast": 1.12,
                    "saturation": 0.78,
                    "temperature": "cool",
                },
                tags=[
                    "horror",
                    "dark",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "visual.vignette_soft"
                ),
                category=EffectCategory.VISUAL,
                display_name="Soft Vignette",
                fallback_preset_id="visual.none",
                implementation={
                    "effect": "vignette",
                    "strength": 0.25,
                },
                tags=[
                    "cinematic",
                    "subtle",
                ],
            ),
            EffectPreset(
                preset_id="animation.none",
                category=EffectCategory.ANIMATION,
                display_name="No Animation",
                implementation={
                    "animation": "none",
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "animation.slow_parallax"
                ),
                category=EffectCategory.ANIMATION,
                display_name="Slow Parallax",
                fallback_preset_id=(
                    "animation.none"
                ),
                implementation={
                    "animation": "parallax",
                    "speed": "slow",
                },
                tags=[
                    "cinematic",
                    "image",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "animation.subtitle_fade"
                ),
                category=EffectCategory.ANIMATION,
                display_name="Subtitle Fade",
                fallback_preset_id=(
                    "animation.none"
                ),
                implementation={
                    "animation": "fade",
                    "target": "subtitle",
                },
                tags=[
                    "subtitle",
                    "subtle",
                ],
            ),
            EffectPreset(
                preset_id="music.none",
                category=EffectCategory.MUSIC,
                display_name="No Background Music",
                implementation={
                    "asset_reference": None,
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id=(
                    "music.horror_low_drone"
                ),
                category=EffectCategory.MUSIC,
                display_name="Horror Low Drone",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": (
                        "dark low suspense drone"
                    ),
                    "loop": True,
                },
                tags=[
                    "horror",
                    "suspense",
                ],
            ),
            EffectPreset(
                preset_id="sfx.none",
                category=(
                    EffectCategory.SOUND_EFFECT
                ),
                display_name="No Sound Effect",
                implementation={
                    "asset_reference": None,
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id="sfx.door_creak",
                category=(
                    EffectCategory.SOUND_EFFECT
                ),
                display_name="Door Creak",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": (
                        "wooden door slow creak"
                    ),
                    "one_shot": True,
                },
                tags=[
                    "horror",
                    "door",
                ],
            ),
            EffectPreset(
                preset_id="sfx.heartbeat_low",
                category=(
                    EffectCategory.SOUND_EFFECT
                ),
                display_name="Low Heartbeat",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": (
                        "slow low heartbeat"
                    ),
                    "one_shot": False,
                },
                tags=[
                    "horror",
                    "tension",
                ],
            ),
            EffectPreset(
                preset_id="subtitle.default",
                category=EffectCategory.SUBTITLE,
                display_name="Default Subtitle",
                implementation={
                    "style": "default",
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id="subtitle.cinematic",
                category=EffectCategory.SUBTITLE,
                display_name="Cinematic Subtitle",
                fallback_preset_id=(
                    "subtitle.default"
                ),
                implementation={
                    "style": "cinematic",
                    "placement": "lower_center",
                },
                tags=[
                    "cinematic",
                ],
            ),
            EffectPreset(
                preset_id="genre.default",
                category=EffectCategory.GENRE,
                display_name="Default Genre",
                implementation={
                    "camera_preset_id": (
                        "camera.none"
                    ),
                    "transition_preset_id": (
                        "transition.cut"
                    ),
                    "visual_preset_ids": [],
                    "music_preset_id": (
                        "music.none"
                    ),
                },
                tags=[
                    "safe",
                    "default",
                ],
            ),
            EffectPreset(
                preset_id="genre.horror",
                category=EffectCategory.GENRE,
                display_name="Horror Genre",
                fallback_preset_id="genre.default",
                implementation={
                    "camera_preset_id": (
                        "camera.slow_zoom_in"
                    ),
                    "transition_preset_id": (
                        "transition.fade_black"
                    ),
                    "visual_preset_ids": [
                        "visual.horror_dark_grade",
                        "visual.vignette_soft",
                    ],
                    "music_preset_id": (
                        "music.horror_low_drone"
                    ),
                },
                tags=[
                    "horror",
                    "suspense",
                ],
            ),
        ]