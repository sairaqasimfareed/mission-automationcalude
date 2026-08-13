from __future__ import annotations

from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.genre_profile import (
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
)


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
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.neutral_narrator"),
                    emotion="neutral",
                    pace=(GenrePacingStyle.MODERATE),
                ),
                editing=GenreEditingProfile(),
                thumbnail=GenreThumbnailProfile(),
                seo=GenreSEOProfile(),
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
                    ],
                    animation_preset_ids=[
                        "animation.slow_parallax",
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
                    visual_preset_ids=[],
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
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.history_narrator"),
                    emotion="serious",
                    pace=(GenrePacingStyle.MODERATE),
                    energy=(DirectiveIntensity.MEDIUM),
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.slow_zoom_in"),
                    transition_in_preset_id=("transition.cross_dissolve"),
                    transition_out_preset_id=("transition.cross_dissolve"),
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
                ),
                voice=GenreVoiceProfile(
                    voice_profile_id=("voice.travel_energetic"),
                    emotion="excited",
                    pace=GenrePacingStyle.FAST,
                    energy=DirectiveIntensity.HIGH,
                ),
                editing=GenreEditingProfile(
                    camera_preset_id=("camera.slow_zoom_in"),
                    transition_in_preset_id=("transition.cross_dissolve"),
                    transition_out_preset_id=("transition.cross_dissolve"),
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
                    camera_preset_id=("camera.slow_zoom_in"),
                    transition_in_preset_id=("transition.cut"),
                    transition_out_preset_id=("transition.cut"),
                    music_preset_id="music.top10_energetic_electronic",
                    sound_effect_preset_ids=[
                        "sfx.whoosh_transition",
                    ],
                    subtitle_preset_id=("subtitle.default"),
                    maximum_active_effects=10,
                    default_transition_duration_seconds=0.0,
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
                    transition_out_preset_id=("transition.cross_dissolve"),
                    visual_preset_ids=[
                        "visual.vignette_soft",
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
                tags=[
                    "storytelling",
                    "emotional",
                    "character",
                ],
            ),
        ]
