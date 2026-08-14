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
        EffectCategory.TRANSITION: ("transition.cut"),
        EffectCategory.VISUAL: "visual.none",
        EffectCategory.ANIMATION: ("animation.none"),
        EffectCategory.MUSIC: "music.none",
        EffectCategory.SOUND_EFFECT: "sfx.none",
        EffectCategory.SUBTITLE: ("subtitle.default"),
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

        existing = self._presets.get(preset.preset_id)

        if existing is not None and not replace:
            raise ValueError(
                "Effect preset is already registered: " f"{preset.preset_id}"
            )

        self._presets[preset.preset_id] = preset

    def unregister(
        self,
        preset_id: str,
    ) -> EffectPreset:
        """Remove and return one registered preset."""

        normalized_id = normalize_effect_id(preset_id)

        if normalized_id not in self._presets:
            raise KeyError("Effect preset is not registered: " f"{normalized_id}")

        return self._presets.pop(normalized_id)

    def get(
        self,
        preset_id: str,
    ) -> EffectPreset:
        """Return one registered preset."""

        normalized_id = normalize_effect_id(preset_id)

        if normalized_id not in self._presets:
            raise KeyError("Effect preset is not registered: " f"{normalized_id}")

        return self._presets[normalized_id]

    def contains(
        self,
        preset_id: str,
    ) -> bool:
        """Return whether one preset is registered."""

        normalized_id = normalize_effect_id(preset_id)

        return normalized_id in self._presets

    def list_all(
        self,
        *,
        active_only: bool = False,
    ) -> list[EffectPreset]:
        """Return all registered presets."""

        presets = list(self._presets.values())

        if active_only:
            presets = [preset for preset in presets if preset.usable]

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

        normalized_id = normalize_effect_id(preset_id)

        exact_preset = self._presets.get(normalized_id)

        if exact_preset is not None and exact_preset.usable:
            return EffectResolutionResult(
                requested_preset_id=normalized_id,
                resolved_preset_id=(exact_preset.preset_id),
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

        fallback_preset = self._presets.get(fallback_id)

        if fallback_preset is None or not fallback_preset.usable:
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
            resolved_preset_id=(fallback_preset.preset_id),
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

        if preset is not None and preset.fallback_preset_id is not None:
            return preset.fallback_preset_id

        category = self._category_from_id(requested_id)

        return self.DEFAULT_FALLBACK_IDS[category]

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
            return "Requested effect preset is not " f"registered: {requested_id}."

        if preset.status == EffectPresetStatus.DISABLED:
            return "Requested effect preset is disabled: " f"{requested_id}."

        return "Requested effect preset is not active: " f"{requested_id}."

    @classmethod
    def with_default_presets(
        cls,
    ) -> EffectRegistryService:
        """Create a registry with safe foundation presets."""

        return cls(presets=cls._build_default_presets())

    @staticmethod
    def _build_default_presets() -> list[EffectPreset]:
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
                category=(EffectCategory.TRANSITION),
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
                preset_id=("transition.fade_black"),
                category=(EffectCategory.TRANSITION),
                display_name="Fade Through Black",
                fallback_preset_id=("transition.cut"),
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
                preset_id=("transition.cross_dissolve"),
                category=(EffectCategory.TRANSITION),
                display_name="Cross Dissolve",
                fallback_preset_id=("transition.cut"),
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
                preset_id=("visual.horror_dark_grade"),
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
                preset_id=("visual.vignette_soft"),
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
                preset_id=("animation.slow_parallax"),
                category=EffectCategory.ANIMATION,
                display_name="Slow Parallax",
                fallback_preset_id=("animation.none"),
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
                preset_id=("animation.subtitle_fade"),
                category=EffectCategory.ANIMATION,
                display_name="Subtitle Fade",
                fallback_preset_id=("animation.none"),
                implementation={
                    "animation": "fade",
                    "target": "subtitle",
                },
                tags=[
                    "subtitle",
                    "subtle",
                ],
            ),
            # --- Camera: additional zoom variants + new pan motion ---
            EffectPreset(
                preset_id="camera.slow_zoom_out",
                category=EffectCategory.CAMERA,
                display_name="Slow Zoom Out",
                fallback_preset_id="camera.none",
                implementation={
                    "motion": "zoom",
                    "direction": "out",
                    "default_start_scale": 1.08,
                    "default_end_scale": 1.0,
                },
                tags=[
                    "cinematic",
                    "documentary",
                ],
            ),
            EffectPreset(
                preset_id="camera.fast_zoom_in",
                category=EffectCategory.CAMERA,
                display_name="Fast Zoom In",
                fallback_preset_id="camera.none",
                implementation={
                    "motion": "zoom",
                    "direction": "in",
                    "default_start_scale": 1.0,
                    "default_end_scale": 1.18,
                },
                tags=[
                    "reaction",
                    "top10",
                    "energetic",
                ],
            ),
            EffectPreset(
                preset_id="camera.pan_left",
                category=EffectCategory.CAMERA,
                display_name="Pan Left",
                fallback_preset_id="camera.none",
                implementation={
                    "motion": "pan",
                    "direction": "left",
                },
                tags=[
                    "cinematic",
                    "horror",
                ],
            ),
            EffectPreset(
                preset_id="camera.pan_right",
                category=EffectCategory.CAMERA,
                display_name="Pan Right",
                fallback_preset_id="camera.none",
                implementation={
                    "motion": "pan",
                    "direction": "right",
                },
                tags=[
                    "cinematic",
                    "travel",
                ],
            ),
            # --- Transitions: additional xfade-native styles ---
            EffectPreset(
                preset_id="transition.wipe_left",
                category=EffectCategory.TRANSITION,
                display_name="Wipe Left",
                fallback_preset_id="transition.cut",
                implementation={
                    "type": "wipe_left",
                    "default_duration_seconds": 0.5,
                },
                tags=[
                    "reaction",
                    "top10",
                ],
            ),
            EffectPreset(
                preset_id="transition.wipe_right",
                category=EffectCategory.TRANSITION,
                display_name="Wipe Right",
                fallback_preset_id="transition.cut",
                implementation={
                    "type": "wipe_right",
                    "default_duration_seconds": 0.5,
                },
                tags=[
                    "reaction",
                    "top10",
                ],
            ),
            EffectPreset(
                preset_id="transition.slide_left",
                category=EffectCategory.TRANSITION,
                display_name="Slide Left",
                fallback_preset_id="transition.cut",
                implementation={
                    "type": "slide_left",
                    "default_duration_seconds": 0.6,
                },
                tags=[
                    "travel",
                    "energetic",
                ],
            ),
            EffectPreset(
                preset_id="transition.circle_crop",
                category=EffectCategory.TRANSITION,
                display_name="Circle Crop",
                fallback_preset_id="transition.cut",
                implementation={
                    "type": "circle_crop",
                    "default_duration_seconds": 0.6,
                },
                tags=[
                    "storytelling",
                    "playful",
                ],
            ),
            EffectPreset(
                preset_id="transition.pixelize",
                category=EffectCategory.TRANSITION,
                display_name="Pixelize",
                fallback_preset_id="transition.cut",
                implementation={
                    "type": "pixelize",
                    "default_duration_seconds": 0.5,
                },
                tags=[
                    "reaction",
                    "top10",
                    "energetic",
                ],
            ),
            # --- Visual effects / filters ---
            EffectPreset(
                preset_id="visual.grayscale",
                category=EffectCategory.VISUAL,
                display_name="Grayscale",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "grayscale",
                },
                tags=[
                    "documentary",
                    "history",
                    "archival",
                ],
            ),
            EffectPreset(
                preset_id="visual.sepia_tone",
                category=EffectCategory.VISUAL,
                display_name="Sepia Tone",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "sepia_tone",
                },
                tags=[
                    "history",
                    "vintage",
                ],
            ),
            EffectPreset(
                preset_id="visual.high_contrast_punch",
                category=EffectCategory.VISUAL,
                display_name="High Contrast Punch",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "high_contrast_punch",
                },
                tags=[
                    "reaction",
                    "top10",
                    "energetic",
                ],
            ),
            EffectPreset(
                preset_id="visual.film_grain_light",
                category=EffectCategory.VISUAL,
                display_name="Light Film Grain",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "film_grain_light",
                },
                tags=[
                    "horror",
                    "mystery",
                    "cinematic",
                ],
            ),
            EffectPreset(
                preset_id="visual.cool_blue_grade",
                category=EffectCategory.VISUAL,
                display_name="Cool Blue Grade",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "cool_blue_grade",
                },
                tags=[
                    "mystery",
                    "medical",
                    "cool",
                ],
            ),
            # --- "LUT" presets: parametric color-grade approximations.
            # No .cube/lut3d engine exists in this codebase - these use
            # the same eq+colorbalance mechanism as the entries above,
            # tagged "lut" for discoverability as cinematic grades.
            EffectPreset(
                preset_id="visual.lut_teal_orange",
                category=EffectCategory.VISUAL,
                display_name="LUT: Teal & Orange",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "lut_teal_orange",
                },
                tags=[
                    "lut",
                    "cinematic",
                    "storytelling",
                ],
            ),
            EffectPreset(
                preset_id="visual.lut_bleach_bypass",
                category=EffectCategory.VISUAL,
                display_name="LUT: Bleach Bypass",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "lut_bleach_bypass",
                },
                tags=[
                    "lut",
                    "survival",
                    "gritty",
                ],
            ),
            EffectPreset(
                preset_id="visual.lut_kodak_warm",
                category=EffectCategory.VISUAL,
                display_name="LUT: Kodak Warm",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "lut_kodak_warm",
                },
                tags=[
                    "lut",
                    "documentary",
                    "warm",
                ],
            ),
            EffectPreset(
                preset_id="visual.lut_moody_desaturated",
                category=EffectCategory.VISUAL,
                display_name="LUT: Moody Desaturated",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "lut_moody_desaturated",
                },
                tags=[
                    "lut",
                    "mystery",
                    "medical",
                ],
            ),
            EffectPreset(
                preset_id="visual.lut_vibrant_punch",
                category=EffectCategory.VISUAL,
                display_name="LUT: Vibrant Punch",
                fallback_preset_id="visual.none",
                implementation={
                    "filter": "lut_vibrant_punch",
                },
                tags=[
                    "lut",
                    "travel",
                    "top10",
                ],
            ),
            # --- Animation: additional motion styles ---
            EffectPreset(
                preset_id="animation.slow_parallax_reverse",
                category=EffectCategory.ANIMATION,
                display_name="Slow Parallax Reverse",
                fallback_preset_id="animation.none",
                implementation={
                    "animation": "parallax",
                    "speed": "slow",
                    "direction": "reverse",
                },
                tags=[
                    "cinematic",
                    "image",
                ],
            ),
            EffectPreset(
                preset_id="animation.slow_pan_vertical",
                category=EffectCategory.ANIMATION,
                display_name="Slow Vertical Pan",
                fallback_preset_id="animation.none",
                implementation={
                    "animation": "pan",
                    "axis": "vertical",
                    "speed": "slow",
                },
                tags=[
                    "cinematic",
                    "image",
                ],
            ),
            EffectPreset(
                preset_id="animation.gentle_zoom_pulse",
                category=EffectCategory.ANIMATION,
                display_name="Gentle Zoom Pulse",
                fallback_preset_id="animation.none",
                implementation={
                    "animation": "zoom_pulse",
                    "speed": "slow",
                },
                tags=[
                    "medical",
                    "mystery",
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
                preset_id=("music.horror_low_drone"),
                category=EffectCategory.MUSIC,
                display_name="Horror Low Drone",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": ("dark low suspense drone"),
                    "loop": True,
                },
                tags=[
                    "horror",
                    "suspense",
                ],
            ),
            EffectPreset(
                preset_id="music.documentary_calm_ambient",
                category=EffectCategory.MUSIC,
                display_name="Documentary Calm Ambient",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "calm ambient documentary background",
                    "loop": True,
                },
                tags=[
                    "documentary",
                    "calm",
                ],
            ),
            EffectPreset(
                preset_id="music.history_dramatic_orchestral",
                category=EffectCategory.MUSIC,
                display_name="History Dramatic Orchestral",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "dramatic orchestral historical narrative",
                    "loop": True,
                },
                tags=[
                    "history",
                    "dramatic",
                ],
            ),
            EffectPreset(
                preset_id="music.travel_upbeat_acoustic",
                category=EffectCategory.MUSIC,
                display_name="Travel Upbeat Acoustic",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "upbeat acoustic travel adventure",
                    "loop": True,
                },
                tags=[
                    "travel",
                    "upbeat",
                ],
            ),
            EffectPreset(
                preset_id="music.top10_energetic_electronic",
                category=EffectCategory.MUSIC,
                display_name="Top 10 Energetic Electronic",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "energetic upbeat electronic countdown",
                    "loop": True,
                },
                tags=[
                    "top10",
                    "energetic",
                ],
            ),
            EffectPreset(
                preset_id="music.storytelling_emotional_piano",
                category=EffectCategory.MUSIC,
                display_name="Storytelling Emotional Piano",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "emotional piano storytelling",
                    "loop": True,
                },
                tags=[
                    "storytelling",
                    "emotional",
                ],
            ),
            EffectPreset(
                preset_id="music.medical_calm_piano",
                category=EffectCategory.MUSIC,
                display_name="Medical Calm Piano",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "calm gentle piano educational",
                    "loop": True,
                },
                tags=[
                    "medical",
                    "calm",
                ],
            ),
            EffectPreset(
                preset_id="music.mystery_tense_strings",
                category=EffectCategory.MUSIC,
                display_name="Mystery Tense Strings",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "tense mystery strings suspense",
                    "loop": True,
                },
                tags=[
                    "mystery",
                    "suspense",
                ],
            ),
            EffectPreset(
                preset_id="music.reaction_upbeat_pop",
                category=EffectCategory.MUSIC,
                display_name="Reaction Upbeat Pop",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "upbeat energetic pop reaction",
                    "loop": True,
                },
                tags=[
                    "reaction",
                    "energetic",
                ],
            ),
            EffectPreset(
                preset_id="music.survival_tense_percussion",
                category=EffectCategory.MUSIC,
                display_name="Survival Tense Percussion",
                fallback_preset_id="music.none",
                implementation={
                    "library_query": "tense tribal percussion survival",
                    "loop": True,
                },
                tags=[
                    "survival",
                    "tense",
                ],
            ),
            EffectPreset(
                preset_id="sfx.none",
                category=(EffectCategory.SOUND_EFFECT),
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
                category=(EffectCategory.SOUND_EFFECT),
                display_name="Door Creak",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": ("wooden door slow creak"),
                    "one_shot": True,
                },
                tags=[
                    "horror",
                    "door",
                ],
            ),
            EffectPreset(
                preset_id="sfx.heartbeat_low",
                category=(EffectCategory.SOUND_EFFECT),
                display_name="Low Heartbeat",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": ("slow low heartbeat"),
                    "one_shot": False,
                },
                tags=[
                    "horror",
                    "tension",
                ],
            ),
            EffectPreset(
                preset_id="sfx.riser_impact",
                category=EffectCategory.SOUND_EFFECT,
                display_name="Riser Impact",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": "cinematic riser impact hit",
                    "one_shot": True,
                },
                tags=[
                    "documentary",
                    "history",
                    "dramatic",
                ],
            ),
            EffectPreset(
                preset_id="sfx.camera_shutter",
                category=EffectCategory.SOUND_EFFECT,
                display_name="Camera Shutter",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": "camera shutter click",
                    "one_shot": True,
                },
                tags=[
                    "travel",
                ],
            ),
            EffectPreset(
                preset_id="sfx.whoosh_transition",
                category=EffectCategory.SOUND_EFFECT,
                display_name="Whoosh Transition",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": "fast whoosh transition swipe",
                    "one_shot": True,
                },
                tags=[
                    "top10",
                ],
            ),
            EffectPreset(
                preset_id="sfx.page_turn",
                category=EffectCategory.SOUND_EFFECT,
                display_name="Page Turn",
                fallback_preset_id="sfx.none",
                implementation={
                    "library_query": "page turn book flip",
                    "one_shot": True,
                },
                tags=[
                    "storytelling",
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
                fallback_preset_id=("subtitle.default"),
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
                    "camera_preset_id": ("camera.none"),
                    "transition_preset_id": ("transition.cut"),
                    "visual_preset_ids": [],
                    "music_preset_id": ("music.none"),
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
                    "camera_preset_id": ("camera.slow_zoom_in"),
                    "transition_preset_id": ("transition.fade_black"),
                    "visual_preset_ids": [
                        "visual.horror_dark_grade",
                        "visual.vignette_soft",
                    ],
                    "music_preset_id": ("music.horror_low_drone"),
                },
                tags=[
                    "horror",
                    "suspense",
                ],
            ),
        ]
