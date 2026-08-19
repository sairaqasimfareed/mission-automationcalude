from __future__ import annotations

from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.genre_profile import (
    CharacterPolicy,
    ConflictingSourcePolicy,
    CTAPolicy,
    GenreContentIntelligenceProfile,
    GenreEditingProfile,
    GenrePacingStyle,
    GenreProfile,
    GenreProfileResolutionResult,
    GenreProfileStatus,
    GenreScriptProfile,
    GenreSEOProfile,
    GenreThumbnailProfile,
    GenreTone,
    GenreVoiceProfile,
    HookArchetype,
    PacingSegment,
    RecapPolicy,
    ResearchDepth,
    ResearchPolicy,
    UncertainInformationPolicy,
)


def _even_pacing_curve() -> list[PacingSegment]:
    """Steady pacing with no dominant peak - documentary/history/medical."""

    return [
        PacingSegment(
            progress_start=0.0,
            progress_end=0.10,
            information_density=40,
            emotional_intensity=35,
            reveal_probability=20,
            tension_level=35,
        ),
        PacingSegment(
            progress_start=0.10,
            progress_end=0.25,
            information_density=50,
            emotional_intensity=40,
            reveal_probability=25,
            tension_level=40,
        ),
        PacingSegment(
            progress_start=0.25,
            progress_end=0.50,
            information_density=55,
            emotional_intensity=45,
            reveal_probability=35,
            tension_level=45,
        ),
        PacingSegment(
            progress_start=0.50,
            progress_end=0.75,
            information_density=55,
            emotional_intensity=50,
            reveal_probability=40,
            tension_level=50,
        ),
        PacingSegment(
            progress_start=0.75,
            progress_end=0.90,
            information_density=50,
            emotional_intensity=55,
            reveal_probability=50,
            tension_level=55,
        ),
        PacingSegment(
            progress_start=0.90,
            progress_end=1.0,
            information_density=35,
            emotional_intensity=45,
            reveal_probability=30,
            tension_level=40,
        ),
    ]


def _front_loaded_pacing_curve() -> list[PacingSegment]:
    """Hooks hard immediately, tapers - travel."""

    return [
        PacingSegment(
            progress_start=0.0,
            progress_end=0.10,
            information_density=60,
            emotional_intensity=70,
            reveal_probability=50,
            tension_level=60,
        ),
        PacingSegment(
            progress_start=0.10,
            progress_end=0.25,
            information_density=55,
            emotional_intensity=60,
            reveal_probability=45,
            tension_level=55,
        ),
        PacingSegment(
            progress_start=0.25,
            progress_end=0.50,
            information_density=50,
            emotional_intensity=50,
            reveal_probability=35,
            tension_level=45,
        ),
        PacingSegment(
            progress_start=0.50,
            progress_end=0.75,
            information_density=45,
            emotional_intensity=45,
            reveal_probability=30,
            tension_level=40,
        ),
        PacingSegment(
            progress_start=0.75,
            progress_end=0.90,
            information_density=40,
            emotional_intensity=40,
            reveal_probability=25,
            tension_level=35,
        ),
        PacingSegment(
            progress_start=0.90,
            progress_end=1.0,
            information_density=35,
            emotional_intensity=50,
            reveal_probability=30,
            tension_level=35,
        ),
    ]


def _back_loaded_pacing_curve() -> list[PacingSegment]:
    """Builds steadily to a late climax - horror/mystery/storytelling/survival."""

    return [
        PacingSegment(
            progress_start=0.0,
            progress_end=0.10,
            information_density=35,
            emotional_intensity=30,
            reveal_probability=15,
            tension_level=25,
        ),
        PacingSegment(
            progress_start=0.10,
            progress_end=0.25,
            information_density=40,
            emotional_intensity=35,
            reveal_probability=20,
            tension_level=30,
        ),
        PacingSegment(
            progress_start=0.25,
            progress_end=0.50,
            information_density=45,
            emotional_intensity=45,
            reveal_probability=30,
            tension_level=45,
        ),
        PacingSegment(
            progress_start=0.50,
            progress_end=0.75,
            information_density=50,
            emotional_intensity=60,
            reveal_probability=40,
            tension_level=60,
        ),
        PacingSegment(
            progress_start=0.75,
            progress_end=0.90,
            information_density=55,
            emotional_intensity=80,
            reveal_probability=65,
            tension_level=85,
        ),
        PacingSegment(
            progress_start=0.90,
            progress_end=1.0,
            information_density=40,
            emotional_intensity=60,
            reveal_probability=50,
            tension_level=55,
        ),
    ]


def _oscillating_pacing_curve() -> list[PacingSegment]:
    """Repeated peaks and valleys - top10/reaction."""

    return [
        PacingSegment(
            progress_start=0.0,
            progress_end=0.10,
            information_density=55,
            emotional_intensity=60,
            reveal_probability=45,
            tension_level=55,
        ),
        PacingSegment(
            progress_start=0.10,
            progress_end=0.25,
            information_density=45,
            emotional_intensity=40,
            reveal_probability=30,
            tension_level=35,
        ),
        PacingSegment(
            progress_start=0.25,
            progress_end=0.50,
            information_density=55,
            emotional_intensity=60,
            reveal_probability=50,
            tension_level=55,
        ),
        PacingSegment(
            progress_start=0.50,
            progress_end=0.75,
            information_density=45,
            emotional_intensity=40,
            reveal_probability=30,
            tension_level=35,
        ),
        PacingSegment(
            progress_start=0.75,
            progress_end=0.90,
            information_density=60,
            emotional_intensity=70,
            reveal_probability=60,
            tension_level=65,
        ),
        PacingSegment(
            progress_start=0.90,
            progress_end=1.0,
            information_density=50,
            emotional_intensity=65,
            reveal_probability=55,
            tension_level=50,
        ),
    ]


class GenreProfileRegistryService:
    """
    Stores and resolves universal production genre profiles.

    Profiles are provider-independent and may be consumed by
    script, voice, editing, thumbnail, and SEO modules.
    """

    DEFAULT_GENRE_ID = "genre.default"

    def __init__(
        self,
        profiles: list[GenreProfile] | None = None,
    ) -> None:
        self._profiles: dict[
            str,
            GenreProfile,
        ] = {}

        for profile in profiles or []:
            self.register(profile)

    def register(
        self,
        profile: GenreProfile,
        *,
        replace: bool = False,
    ) -> None:
        """Register one genre profile."""

        existing = self._profiles.get(profile.genre_id)

        if existing is not None and not replace:
            raise ValueError(
                "Genre profile is already registered: " f"{profile.genre_id}"
            )

        self._profiles[profile.genre_id] = profile

    def unregister(
        self,
        genre_id: str,
    ) -> GenreProfile:
        """Remove and return one registered profile."""

        normalized_id = self._normalize_genre_id(genre_id)

        if normalized_id not in self._profiles:
            raise KeyError("Genre profile is not registered: " f"{normalized_id}")

        if normalized_id == self.DEFAULT_GENRE_ID:
            raise ValueError("The default genre profile cannot " "be unregistered.")

        return self._profiles.pop(normalized_id)

    def get(
        self,
        genre_id: str,
    ) -> GenreProfile:
        """Return one registered profile."""

        normalized_id = self._normalize_genre_id(genre_id)

        if normalized_id not in self._profiles:
            raise KeyError("Genre profile is not registered: " f"{normalized_id}")

        return self._profiles[normalized_id]

    def contains(
        self,
        genre_id: str,
    ) -> bool:
        """Return whether one genre profile exists."""

        normalized_id = self._normalize_genre_id(genre_id)

        return normalized_id in self._profiles

    def list_all(
        self,
        *,
        active_only: bool = False,
    ) -> list[GenreProfile]:
        """Return all genre profiles in stable order."""

        profiles = list(self._profiles.values())

        if active_only:
            profiles = [profile for profile in profiles if profile.usable]

        return sorted(
            profiles,
            key=lambda profile: (
                profile.display_name.lower(),
                profile.genre_id,
            ),
        )

    def resolve(
        self,
        genre_id: str,
        *,
        allow_fallback: bool = True,
    ) -> GenreProfileResolutionResult:
        """Resolve one genre profile with a safe fallback."""

        normalized_id = self._normalize_genre_id(genre_id)

        exact_profile = self._profiles.get(normalized_id)

        if exact_profile is not None and exact_profile.usable:
            return GenreProfileResolutionResult(
                requested_genre_id=normalized_id,
                resolved_genre_id=(exact_profile.genre_id),
                profile=exact_profile,
                found_exact_match=True,
                used_fallback=False,
            )

        warning = self._build_unresolved_warning(
            genre_id=normalized_id,
            profile=exact_profile,
        )

        if not allow_fallback:
            return GenreProfileResolutionResult(
                requested_genre_id=normalized_id,
                warning=warning,
            )

        fallback_id = (
            exact_profile.fallback_genre_id
            if (
                exact_profile is not None
                and exact_profile.fallback_genre_id is not None
            )
            else self.DEFAULT_GENRE_ID
        )

        fallback_profile = self._profiles.get(fallback_id)

        if fallback_profile is None or not fallback_profile.usable:
            return GenreProfileResolutionResult(
                requested_genre_id=normalized_id,
                warning=(
                    warning + " No usable fallback genre " "profile is registered."
                ),
            )

        return GenreProfileResolutionResult(
            requested_genre_id=normalized_id,
            resolved_genre_id=(fallback_profile.genre_id),
            profile=fallback_profile,
            found_exact_match=False,
            used_fallback=True,
            warning=(
                warning + " Safe fallback "
                f"'{fallback_profile.genre_id}' "
                "was selected."
            ),
        )

    @classmethod
    def with_default_profiles(
        cls,
    ) -> GenreProfileRegistryService:
        """Create a registry with built-in profiles."""

        return cls(profiles=cls._build_default_profiles())

    @staticmethod
    def _normalize_genre_id(
        genre_id: str,
    ) -> str:
        """Normalize a genre identifier."""

        normalized = genre_id.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre profile ID must start " "with 'genre.'.")

        if normalized == "genre.":
            raise ValueError("Genre profile ID requires a name.")

        allowed_characters = set("abcdefghijklmnopqrstuvwxyz" "0123456789._-")

        if any(character not in allowed_characters for character in normalized):
            raise ValueError("Genre profile ID contains " "unsupported characters.")

        return normalized

    @staticmethod
    def _build_unresolved_warning(
        *,
        genre_id: str,
        profile: GenreProfile | None,
    ) -> str:
        """Build a genre resolution warning."""

        if profile is None:
            return "Requested genre profile is not " f"registered: {genre_id}."

        if profile.status == GenreProfileStatus.DISABLED:
            return "Requested genre profile is disabled: " f"{genre_id}."

        return "Requested genre profile is not active: " f"{genre_id}."

    @staticmethod
    def _build_default_profiles() -> list[GenreProfile]:
        """Return initial built-in universal genre profiles."""

        return [
            GenreProfile(
                genre_id="genre.default",
                display_name="Default",
                description=("Safe and neutral production defaults."),
                fallback_genre_id=None,
                script=GenreScriptProfile(
                    tone=GenreTone.NEUTRAL,
                    pacing=(GenrePacingStyle.MODERATE),
                    hook_style="standard",
                    narrative_style="informative",
                    sentence_length="medium",
                    slang_intensity=DirectiveIntensity.LOW,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.neutral_narrator"),
                    emotion="neutral",
                    pace=(GenrePacingStyle.MODERATE),
                ),
                editing=GenreEditingProfile(),
                thumbnail=GenreThumbnailProfile(),
                seo=GenreSEOProfile(),
                content_intelligence=GenreContentIntelligenceProfile(
                    narrative_architecture_hint=(
                        "Hook -> context -> development -> "
                        "climax/insight -> resolution."
                    ),
                    pacing_curve=_even_pacing_curve(),
                    quality_thresholds={
                        "factual_confidence": 40,
                        "hook_strength": 35,
                    },
                ),
                tags=[
                    "safe",
                    "default",
                ],
            ),
            GenreProfile(
                genre_id="genre.horror",
                display_name="Horror",
                description=(
                    "Dark, suspenseful and cinematic " "storytelling profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.SUSPENSEFUL,
                    pacing=GenrePacingStyle.SLOW,
                    hook_style="mystery_shock",
                    narrative_style=("cinematic_suspense"),
                    sentence_length="short",
                    use_cliffhangers=True,
                    use_open_loops=True,
                    emotional_intensity=(DirectiveIntensity.HIGH),
                    slang_intensity=DirectiveIntensity.MEDIUM,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.horror_whisper"),
                    emotion="tense",
                    pace=GenrePacingStyle.SLOW,
                    energy=DirectiveIntensity.LOW,
                    pitch_style="deep",
                    pause_style="dramatic",
                    emphasis_style="selective",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.slow_zoom_in"),
                    transition_in_preset_id=("transition.fade_black"),
                    transition_out_preset_id=("transition.fade_black"),
                    visual_preset_ids=[
                        "visual.horror_dark_grade",
                        "visual.vignette_soft",
                        "visual.film_grain_light",
                    ],
                    animation_preset_ids=[
                        "animation.slow_parallax",
                        "animation.gentle_zoom_pulse",
                    ],
                    music_preset_id=("music.horror_low_drone"),
                    sound_effect_preset_ids=[
                        "sfx.door_creak",
                        "sfx.heartbeat_low",
                    ],
                    subtitle_preset_id=("subtitle.cinematic"),
                    subtitle_animation_preset_id=("animation.subtitle_fade"),
                    effect_intensity=(DirectiveIntensity.MEDIUM),
                    maximum_active_effects=8,
                    default_transition_duration_seconds=0.8,
                    default_music_volume_percent=25.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.horror",
                    composition="single_focal_subject",
                    color_mood="dark_high_contrast",
                    text_style="bold_mystery",
                    use_faces=False,
                    maximum_words=4,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.SUSPENSEFUL,
                    description_style=("mystery_story_summary"),
                    keyword_style="horror_specific",
                    hashtag_style="dark_storytelling",
                    call_to_action_style=("suspense_question"),
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "horror",
                        "mystery",
                        "revelation_driven",
                    ],
                    narrative_architecture_hint=(
                        "Disturbance -> curiosity -> unease -> escalation -> "
                        "temporary relief -> stronger threat -> revelation -> "
                        "climax -> aftermath."
                    ),
                    pacing_curve=_back_loaded_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.DISTURBING_EVENT,
                        HookArchetype.MYSTERY,
                        HookArchetype.UNANSWERED_QUESTION,
                    ],
                    forbidden_hook_archetypes=[
                        HookArchetype.RANKED_LIST_PROMISE,
                    ],
                    hook_intensity=DirectiveIntensity.HIGH,
                    reveal_density_per_minute=3.0,
                    pattern_interrupt_frequency=DirectiveIntensity.MEDIUM,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.LOW,
                        minimum_source_count=0,
                        uncertain_information_policy=(
                            UncertainInformationPolicy.USE_FREELY
                        ),
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    forbidden_cta_positions=["climax"],
                    quality_thresholds={
                        "retention_architecture": 55,
                        "hook_strength": 60,
                        "emotional_progression": 55,
                    },
                    character_policy=CharacterPolicy(
                        requires_protagonist=True,
                        requires_antagonist_or_conflict=True,
                        allow_dialogue=True,
                        maximum_character_count=4,
                    ),
                    scene_density_per_minute=8.0,
                    average_visual_duration_seconds=5.0,
                ),
                tags=[
                    "horror",
                    "suspense",
                    "dark",
                ],
            ),
            GenreProfile(
                genre_id="genre.documentary",
                display_name="Documentary",
                description=(
                    "Clear, authoritative and informative " "documentary profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.AUTHORITATIVE,
                    pacing=(GenrePacingStyle.MODERATE),
                    hook_style="fact_reveal",
                    narrative_style=("evidence_based"),
                    sentence_length="medium",
                    use_open_loops=True,
                    slang_intensity=DirectiveIntensity.VERY_LOW,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.documentary_authoritative"),
                    emotion="serious",
                    pace=(GenrePacingStyle.MODERATE),
                    energy=(DirectiveIntensity.MEDIUM),
                    pause_style="natural",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.slow_zoom_in"),
                    transition_in_preset_id=("transition.cross_dissolve"),
                    transition_out_preset_id=("transition.cross_dissolve"),
                    visual_preset_ids=[
                        "visual.lut_kodak_warm",
                    ],
                    music_preset_id="music.documentary_calm_ambient",
                    sound_effect_preset_ids=[
                        "sfx.riser_impact",
                    ],
                    subtitle_preset_id=("subtitle.cinematic"),
                    default_transition_duration_seconds=0.6,
                    default_music_volume_percent=18.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id=("thumbnail.documentary"),
                    composition="subject_and_context",
                    color_mood="natural_cinematic",
                    text_style="authoritative",
                    maximum_words=5,
                ),
                seo=GenreSEOProfile(
                    title_tone=(GenreTone.AUTHORITATIVE),
                    description_style=("factual_overview"),
                    keyword_style=("topic_authority"),
                    hashtag_style="informative",
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "documentary",
                        "chronological",
                        "investigation",
                    ],
                    narrative_architecture_hint=(
                        "Hook/contradiction -> central question -> context -> "
                        "evidence -> development -> complication -> discovery "
                        "-> consequence -> conclusion."
                    ),
                    pacing_curve=_even_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.CONTRADICTION,
                        HookArchetype.SHOCKING_FACT,
                        HookArchetype.UNANSWERED_QUESTION,
                    ],
                    forbidden_hook_archetypes=[
                        HookArchetype.RANKED_LIST_PROMISE,
                        HookArchetype.TRANSFORMATION,
                    ],
                    hook_intensity=DirectiveIntensity.MEDIUM,
                    reveal_density_per_minute=1.5,
                    pattern_interrupt_frequency=DirectiveIntensity.LOW,
                    recap_policy=RecapPolicy.BRIEF,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.HIGH,
                        minimum_source_count=5,
                        requires_primary_sources=True,
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    quality_thresholds={
                        "factual_confidence": 65,
                        "research_grounding": 65,
                        "narrative_coherence": 50,
                    },
                    scene_density_per_minute=5.0,
                    average_visual_duration_seconds=8.0,
                    establishing_shot_policy="frequent",
                ),
                tags=[
                    "documentary",
                    "educational",
                    "informative",
                ],
            ),
            GenreProfile(
                genre_id="genre.history",
                display_name="History",
                description=(
                    "Cinematic historical storytelling " "and educational profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.CINEMATIC,
                    pacing=(GenrePacingStyle.MODERATE),
                    hook_style="historical_reveal",
                    narrative_style=("chronological_storytelling"),
                    sentence_length="medium",
                    use_open_loops=True,
                    slang_intensity=DirectiveIntensity.VERY_LOW,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.history_narrator"),
                    emotion="serious",
                    pace=(GenrePacingStyle.MODERATE),
                    energy=(DirectiveIntensity.MEDIUM),
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.slow_zoom_out"),
                    transition_in_preset_id=("transition.cross_dissolve"),
                    transition_out_preset_id=("transition.cross_dissolve"),
                    visual_preset_ids=[
                        "visual.grayscale",
                        "visual.sepia_tone",
                    ],
                    music_preset_id="music.history_dramatic_orchestral",
                    sound_effect_preset_ids=[
                        "sfx.riser_impact",
                    ],
                    subtitle_preset_id=("subtitle.cinematic"),
                    default_transition_duration_seconds=0.6,
                    default_music_volume_percent=20.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.history",
                    composition="historic_subject",
                    color_mood="warm_aged",
                    text_style="bold_historical",
                    maximum_words=5,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.CINEMATIC,
                    description_style=("historical_context"),
                    keyword_style=("historical_entities"),
                    hashtag_style="history_topics",
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "documentary",
                        "chronological",
                        "revelation_driven",
                        "reverse_chronology",
                    ],
                    narrative_architecture_hint=(
                        "Hook/contradiction -> historical context -> "
                        "chronological development -> turning point -> "
                        "consequence -> legacy/conclusion."
                    ),
                    pacing_curve=_even_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.SHOCKING_FACT,
                        HookArchetype.MYSTERY,
                        HookArchetype.DRAMATIC_MOMENT,
                    ],
                    hook_intensity=DirectiveIntensity.MEDIUM,
                    reveal_density_per_minute=1.8,
                    recap_policy=RecapPolicy.BRIEF,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.HIGH,
                        minimum_source_count=4,
                        requires_primary_sources=True,
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    quality_thresholds={
                        "factual_confidence": 60,
                        "research_grounding": 60,
                        "narrative_coherence": 50,
                    },
                    character_policy=CharacterPolicy(
                        allow_dialogue=False,
                        maximum_character_count=3,
                    ),
                    scene_density_per_minute=5.5,
                    average_visual_duration_seconds=7.0,
                    establishing_shot_policy="frequent",
                ),
                tags=[
                    "history",
                    "educational",
                    "cinematic",
                ],
            ),
            GenreProfile(
                genre_id="genre.travel",
                display_name="Travel",
                description=(
                    "Bright, inspiring and destination-focused " "travel profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.INSPIRATIONAL,
                    pacing=GenrePacingStyle.FAST,
                    hook_style="destination_wonder",
                    narrative_style=("descriptive_guide"),
                    sentence_length="short",
                    slang_intensity=DirectiveIntensity.HIGH,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.travel_energetic"),
                    emotion="excited",
                    pace=GenrePacingStyle.FAST,
                    energy=DirectiveIntensity.HIGH,
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.pan_right"),
                    transition_in_preset_id=("transition.slide_left"),
                    transition_out_preset_id=("transition.slide_left"),
                    visual_preset_ids=[
                        "visual.lut_vibrant_punch",
                    ],
                    music_preset_id="music.travel_upbeat_acoustic",
                    sound_effect_preset_ids=[
                        "sfx.camera_shutter",
                    ],
                    subtitle_preset_id=("subtitle.default"),
                    default_transition_duration_seconds=0.5,
                    default_music_volume_percent=30.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.travel",
                    composition="wide_destination",
                    color_mood="bright_vibrant",
                    text_style="destination_bold",
                    maximum_words=4,
                ),
                seo=GenreSEOProfile(
                    title_tone=(GenreTone.INSPIRATIONAL),
                    description_style=("destination_guide"),
                    keyword_style=("location_and_activity"),
                    hashtag_style="travel_discovery",
                    call_to_action_style=("plan_your_trip"),
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "character_pov",
                        "chronological",
                        "emotional",
                    ],
                    narrative_architecture_hint=(
                        "Destination promise -> visual hook -> experience -> "
                        "why it matters -> practical insight -> next "
                        "destination."
                    ),
                    pacing_curve=_front_loaded_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.DRAMATIC_MOMENT,
                        HookArchetype.FUTURE_PAYOFF,
                    ],
                    hook_intensity=DirectiveIntensity.MEDIUM,
                    reveal_density_per_minute=1.5,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.MODERATE,
                        minimum_source_count=3,
                    ),
                    cta_policy=CTAPolicy.DIRECT,
                    quality_thresholds={
                        "audience_fit": 50,
                        "visual_opportunity_density": 60,
                    },
                    scene_density_per_minute=8.0,
                    average_visual_duration_seconds=5.0,
                    b_roll_density=DirectiveIntensity.HIGH,
                    establishing_shot_policy="frequent",
                ),
                tags=[
                    "travel",
                    "destination",
                    "inspirational",
                ],
            ),
            GenreProfile(
                genre_id="genre.top10",
                display_name="Top 10",
                description=(
                    "Fast, energetic and countdown-based " "list video profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.ENERGETIC,
                    pacing=(GenrePacingStyle.VERY_FAST),
                    hook_style="countdown_tease",
                    narrative_style="ranked_list",
                    sentence_length="short",
                    use_open_loops=True,
                    slang_intensity=DirectiveIntensity.HIGH,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.top10_energetic"),
                    emotion="excited",
                    pace=(GenrePacingStyle.VERY_FAST),
                    energy=(DirectiveIntensity.VERY_HIGH),
                    pause_style="short",
                    emphasis_style="rank_numbers",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.fast_zoom_in"),
                    transition_in_preset_id=("transition.wipe_left"),
                    transition_out_preset_id=("transition.pixelize"),
                    visual_preset_ids=[
                        "visual.high_contrast_punch",
                    ],
                    music_preset_id="music.top10_energetic_electronic",
                    sound_effect_preset_ids=[
                        "sfx.whoosh_transition",
                    ],
                    subtitle_preset_id=("subtitle.default"),
                    maximum_active_effects=10,
                    default_transition_duration_seconds=0.35,
                    default_music_volume_percent=32.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.top10",
                    composition="number_and_subject",
                    color_mood="bright_high_contrast",
                    text_style="large_number",
                    maximum_words=4,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.ENERGETIC,
                    description_style="list_summary",
                    keyword_style="ranked_keywords",
                    hashtag_style="list_discovery",
                    call_to_action_style=("ask_favorite_item"),
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "question_driven",
                        "chronological",
                    ],
                    narrative_architecture_hint=(
                        "Strong promise -> ranking setup -> #10 -> "
                        "escalating entries -> pattern interrupts -> "
                        "increasingly strong entries -> #1 payoff -> "
                        "conclusion."
                    ),
                    pacing_curve=_oscillating_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.RANKED_LIST_PROMISE,
                        HookArchetype.FUTURE_PAYOFF,
                    ],
                    hook_intensity=DirectiveIntensity.HIGH,
                    reveal_density_per_minute=4.0,
                    pattern_interrupt_frequency=DirectiveIntensity.HIGH,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.MODERATE,
                        minimum_source_count=3,
                    ),
                    cta_policy=CTAPolicy.DIRECT,
                    quality_thresholds={
                        "retention_architecture": 55,
                        "hook_strength": 55,
                    },
                    scene_density_per_minute=10.0,
                    average_visual_duration_seconds=5.0,
                    b_roll_density=DirectiveIntensity.HIGH,
                ),
                tags=[
                    "top10",
                    "list",
                    "energetic",
                ],
            ),
            GenreProfile(
                genre_id="genre.storytelling",
                display_name="Storytelling",
                description=(
                    "Emotional, immersive and character-led " "storytelling profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.EMOTIONAL,
                    pacing=GenrePacingStyle.DYNAMIC,
                    hook_style="emotional_conflict",
                    narrative_style=("character_driven"),
                    sentence_length="variable",
                    use_cliffhangers=True,
                    use_open_loops=True,
                    emotional_intensity=(DirectiveIntensity.HIGH),
                    slang_intensity=DirectiveIntensity.MEDIUM,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.warm_storyteller"),
                    emotion="expressive",
                    pace=GenrePacingStyle.DYNAMIC,
                    energy=DirectiveIntensity.MEDIUM,
                    pause_style="dramatic",
                    emphasis_style="emotional",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.slow_zoom_in"),
                    transition_in_preset_id=("transition.cross_dissolve"),
                    transition_out_preset_id=("transition.circle_crop"),
                    visual_preset_ids=[
                        "visual.vignette_soft",
                        "visual.lut_teal_orange",
                    ],
                    music_preset_id="music.storytelling_emotional_piano",
                    sound_effect_preset_ids=[
                        "sfx.page_turn",
                    ],
                    subtitle_preset_id=("subtitle.cinematic"),
                    subtitle_animation_preset_id=("animation.subtitle_fade"),
                    default_transition_duration_seconds=0.6,
                    default_music_volume_percent=24.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id=("thumbnail.storytelling"),
                    composition="emotional_subject",
                    color_mood="cinematic_emotional",
                    text_style="story_hook",
                    use_faces=True,
                    maximum_words=5,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.EMOTIONAL,
                    description_style="story_summary",
                    keyword_style=("character_and_conflict"),
                    hashtag_style="storytelling",
                    call_to_action_style=("emotional_question"),
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "character_pov",
                        "emotional",
                        "revelation_driven",
                    ],
                    narrative_architecture_hint=(
                        "Emotional conflict -> relationship context -> small "
                        "conflict -> escalation -> betrayal/humiliation -> "
                        "backstory -> confrontation -> revelation -> "
                        "emotional payoff -> resolution."
                    ),
                    pacing_curve=_back_loaded_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.EMOTIONAL_CONFLICT,
                        HookArchetype.DISTURBING_EVENT,
                        HookArchetype.UNANSWERED_QUESTION,
                    ],
                    hook_intensity=DirectiveIntensity.HIGH,
                    reveal_density_per_minute=2.5,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.LOW,
                        minimum_source_count=0,
                        uncertain_information_policy=(
                            UncertainInformationPolicy.USE_FREELY
                        ),
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    quality_thresholds={
                        "emotional_progression": 60,
                        "character_depth": 55,
                        "payoff_strength": 55,
                    },
                    character_policy=CharacterPolicy(
                        requires_protagonist=True,
                        requires_antagonist_or_conflict=True,
                        allow_dialogue=True,
                        maximum_character_count=5,
                    ),
                    scene_density_per_minute=6.5,
                ),
                tags=[
                    "storytelling",
                    "emotional",
                    "character",
                ],
            ),
            GenreProfile(
                genre_id="genre.medical",
                display_name="Medical",
                description=(
                    "Calm, authoritative medical and health "
                    "information profile with restrained presentation."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.AUTHORITATIVE,
                    pacing=GenrePacingStyle.MODERATE,
                    hook_style="informative",
                    narrative_style="explanatory",
                    sentence_length="medium",
                    emotional_intensity=DirectiveIntensity.LOW,
                    slang_intensity=DirectiveIntensity.VERY_LOW,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id="voice.neutral_narrator",
                    emotion="calm",
                    pace=GenrePacingStyle.MODERATE,
                    energy=DirectiveIntensity.LOW,
                    pitch_style="natural",
                    pause_style="natural",
                    emphasis_style="balanced",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id="camera.none",
                    transition_in_preset_id="transition.cross_dissolve",
                    transition_out_preset_id="transition.cross_dissolve",
                    visual_preset_ids=[
                        "visual.cool_blue_grade",
                    ],
                    music_preset_id="music.medical_calm_piano",
                    subtitle_preset_id="subtitle.cinematic",
                    default_transition_duration_seconds=0.6,
                    default_music_volume_percent=15.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.medical",
                    composition="subject_and_context",
                    color_mood="clean_clinical",
                    text_style="clear_authoritative",
                    use_faces=False,
                    maximum_words=5,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.AUTHORITATIVE,
                    description_style="factual_overview",
                    keyword_style="topic_authority",
                    hashtag_style="informative",
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "documentary",
                        "question_driven",
                    ],
                    narrative_architecture_hint=(
                        "Central question -> context -> evidence -> "
                        "development -> caveats/uncertainty -> practical "
                        "takeaway -> conclusion."
                    ),
                    pacing_curve=_even_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.SHOCKING_FACT,
                        HookArchetype.CONTRADICTION,
                    ],
                    forbidden_hook_archetypes=[
                        HookArchetype.RANKED_LIST_PROMISE,
                        HookArchetype.TRANSFORMATION,
                    ],
                    hook_intensity=DirectiveIntensity.LOW,
                    reveal_density_per_minute=1.2,
                    recap_policy=RecapPolicy.BRIEF,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.VERY_HIGH,
                        minimum_source_count=6,
                        requires_primary_sources=True,
                        uncertain_information_policy=(
                            UncertainInformationPolicy.EXCLUDE
                        ),
                        conflicting_source_policy=(
                            ConflictingSourcePolicy.FLAG_CONTROVERSY
                        ),
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    quality_thresholds={
                        "factual_confidence": 75,
                        "research_grounding": 70,
                    },
                    scene_density_per_minute=4.0,
                    average_visual_duration_seconds=9.0,
                ),
                tags=[
                    "medical",
                    "educational",
                    "health",
                ],
            ),
            GenreProfile(
                genre_id="genre.mystery",
                display_name="Mystery",
                description=(
                    "Suspense-driven investigative storytelling "
                    "with controlled reveals and open loops."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.SUSPENSEFUL,
                    pacing=GenrePacingStyle.MODERATE,
                    hook_style="cliffhanger",
                    narrative_style="investigative",
                    sentence_length="medium",
                    use_cliffhangers=True,
                    use_open_loops=True,
                    emotional_intensity=DirectiveIntensity.MEDIUM,
                    slang_intensity=DirectiveIntensity.MEDIUM,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id="voice.neutral_narrator",
                    emotion="mysterious",
                    pace=GenrePacingStyle.MODERATE,
                    energy=DirectiveIntensity.MEDIUM,
                    pitch_style="deep",
                    pause_style="dramatic",
                    emphasis_style="selective",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id="camera.pan_left",
                    transition_in_preset_id="transition.fade_black",
                    transition_out_preset_id="transition.fade_black",
                    visual_preset_ids=[
                        "visual.vignette_soft",
                        "visual.lut_moody_desaturated",
                    ],
                    animation_preset_ids=[
                        "animation.slow_parallax_reverse",
                    ],
                    music_preset_id="music.mystery_tense_strings",
                    sound_effect_preset_ids=[
                        "sfx.riser_impact",
                    ],
                    subtitle_preset_id="subtitle.cinematic",
                    subtitle_animation_preset_id="animation.subtitle_fade",
                    default_transition_duration_seconds=0.7,
                    default_music_volume_percent=22.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.mystery",
                    composition="single_focal_subject",
                    color_mood="dark_high_contrast",
                    text_style="bold_mystery",
                    use_faces=False,
                    maximum_words=4,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.SUSPENSEFUL,
                    description_style="intriguing_teaser",
                    keyword_style="curiosity_driven",
                    hashtag_style="mystery",
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "mystery",
                        "investigation",
                        "revelation_driven",
                        "question_driven",
                    ],
                    narrative_architecture_hint=(
                        "Mystery -> known facts -> contradiction -> evidence "
                        "-> new question -> hidden connection -> major "
                        "reveal -> counterargument -> evidence evaluation -> "
                        "conclusion."
                    ),
                    pacing_curve=_back_loaded_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.MYSTERY,
                        HookArchetype.CONTRADICTION,
                        HookArchetype.UNANSWERED_QUESTION,
                    ],
                    forbidden_hook_archetypes=[
                        HookArchetype.RANKED_LIST_PROMISE,
                    ],
                    hook_intensity=DirectiveIntensity.HIGH,
                    reveal_density_per_minute=3.0,
                    pattern_interrupt_frequency=DirectiveIntensity.MEDIUM,
                    recap_policy=RecapPolicy.BRIEF,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.HIGH,
                        minimum_source_count=4,
                        requires_primary_sources=True,
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    forbidden_cta_positions=["climax"],
                    quality_thresholds={
                        "factual_confidence": 55,
                        "retention_architecture": 60,
                        "hook_strength": 55,
                    },
                    character_policy=CharacterPolicy(
                        allow_dialogue=False,
                        maximum_character_count=3,
                    ),
                    scene_density_per_minute=6.5,
                ),
                tags=[
                    "mystery",
                    "suspense",
                    "investigation",
                ],
            ),
            GenreProfile(
                genre_id="genre.reaction",
                display_name="Reaction",
                description=(
                    "Fast, conversational commentary-led reaction " "video profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.ENERGETIC,
                    pacing=GenrePacingStyle.FAST,
                    hook_style="conversational",
                    narrative_style="commentary",
                    sentence_length="short",
                    emotional_intensity=DirectiveIntensity.HIGH,
                    slang_intensity=DirectiveIntensity.HIGH,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id="voice.neutral_narrator",
                    emotion="excited",
                    pace=GenrePacingStyle.FAST,
                    energy=DirectiveIntensity.HIGH,
                    pitch_style="bright",
                    pause_style="minimal",
                    emphasis_style="dramatic",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id="camera.none",
                    transition_in_preset_id="transition.cut",
                    transition_out_preset_id="transition.wipe_right",
                    visual_preset_ids=[
                        "visual.high_contrast_punch",
                    ],
                    music_preset_id="music.reaction_upbeat_pop",
                    sound_effect_preset_ids=[
                        "sfx.whoosh_transition",
                    ],
                    subtitle_preset_id="subtitle.default",
                    maximum_active_effects=10,
                    default_transition_duration_seconds=0.3,
                    default_music_volume_percent=20.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.reaction",
                    composition="subject_and_context",
                    color_mood="bright_vibrant",
                    text_style="bold_expressive",
                    use_faces=True,
                    maximum_words=4,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.ENERGETIC,
                    description_style="conversational",
                    keyword_style="trending",
                    hashtag_style="trending",
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "character_pov",
                        "question_driven",
                    ],
                    narrative_architecture_hint=(
                        "Cold open reaction -> commentary context -> "
                        "escalating reactions -> pattern interrupts -> "
                        "capstone reaction -> wrap-up."
                    ),
                    pacing_curve=_oscillating_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.DRAMATIC_MOMENT,
                        HookArchetype.COLD_OPEN,
                    ],
                    hook_intensity=DirectiveIntensity.HIGH,
                    reveal_density_per_minute=3.5,
                    pattern_interrupt_frequency=DirectiveIntensity.HIGH,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.LOW,
                        minimum_source_count=0,
                        uncertain_information_policy=(
                            UncertainInformationPolicy.USE_FREELY
                        ),
                    ),
                    cta_policy=CTAPolicy.DIRECT,
                    quality_thresholds={
                        "audience_fit": 45,
                        "hook_strength": 45,
                    },
                    scene_density_per_minute=9.0,
                    average_visual_duration_seconds=4.5,
                ),
                tags=[
                    "reaction",
                    "commentary",
                    "entertainment",
                ],
            ),
            GenreProfile(
                genre_id="genre.survival",
                display_name="Survival",
                description=(
                    "Tense, practical and cinematic survival "
                    "storytelling and preparedness profile."
                ),
                script=GenreScriptProfile(
                    tone=GenreTone.DARK,
                    pacing=GenrePacingStyle.MODERATE,
                    hook_style="urgent",
                    narrative_style="practical",
                    sentence_length="medium",
                    use_cliffhangers=True,
                    emotional_intensity=DirectiveIntensity.HIGH,
                    slang_intensity=DirectiveIntensity.MEDIUM,
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id="voice.neutral_narrator",
                    emotion="serious",
                    pace=GenrePacingStyle.MODERATE,
                    energy=DirectiveIntensity.HIGH,
                    pitch_style="deep",
                    pause_style="dramatic",
                    emphasis_style="dramatic",
                ),
                editing=GenreEditingProfile(
                    camera_preset_id="camera.slow_zoom_in",
                    transition_in_preset_id="transition.fade_black",
                    transition_out_preset_id="transition.fade_black",
                    visual_preset_ids=[
                        "visual.horror_dark_grade",
                        "visual.lut_bleach_bypass",
                    ],
                    animation_preset_ids=[
                        "animation.slow_pan_vertical",
                    ],
                    music_preset_id="music.survival_tense_percussion",
                    sound_effect_preset_ids=[
                        "sfx.riser_impact",
                    ],
                    subtitle_preset_id="subtitle.cinematic",
                    subtitle_animation_preset_id="animation.subtitle_fade",
                    default_transition_duration_seconds=0.7,
                    default_music_volume_percent=22.0,
                ),
                thumbnail=GenreThumbnailProfile(
                    style_id="thumbnail.survival",
                    composition="wide_destination",
                    color_mood="dark_high_contrast",
                    text_style="bold_survival",
                    use_faces=False,
                    maximum_words=4,
                ),
                seo=GenreSEOProfile(
                    title_tone=GenreTone.DARK,
                    description_style="urgent_practical",
                    keyword_style="practical_howto",
                    hashtag_style="survival",
                ),
                content_intelligence=GenreContentIntelligenceProfile(
                    preferred_angle_styles=[
                        "character_pov",
                        "chronological",
                        "revelation_driven",
                    ],
                    narrative_architecture_hint=(
                        "Disturbance/threat -> stakes established -> "
                        "practical response -> escalation -> setback -> "
                        "adaptation -> resolution -> lesson/aftermath."
                    ),
                    pacing_curve=_back_loaded_pacing_curve(),
                    preferred_hook_archetypes=[
                        HookArchetype.DISTURBING_EVENT,
                        HookArchetype.DRAMATIC_MOMENT,
                        HookArchetype.FUTURE_PAYOFF,
                    ],
                    hook_intensity=DirectiveIntensity.HIGH,
                    reveal_density_per_minute=2.0,
                    research_policy=ResearchPolicy(
                        depth=ResearchDepth.MODERATE,
                        minimum_source_count=3,
                    ),
                    cta_policy=CTAPolicy.SOFT,
                    quality_thresholds={
                        "retention_architecture": 50,
                        "emotional_progression": 50,
                    },
                    character_policy=CharacterPolicy(
                        requires_protagonist=True,
                        requires_antagonist_or_conflict=True,
                        allow_dialogue=False,
                        maximum_character_count=3,
                    ),
                    scene_density_per_minute=6.5,
                ),
                tags=[
                    "survival",
                    "preparedness",
                    "outdoors",
                ],
            ),
        ]
