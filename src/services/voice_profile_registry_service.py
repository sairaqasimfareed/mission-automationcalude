from __future__ import annotations

from copy import deepcopy

from src.models.voice_directives import (
    VoiceEmotion,
    VoiceEmphasisStyle,
    VoiceEnergy,
    VoicePace,
    VoicePauseStyle,
    VoicePitchStyle,
)
from src.models.voice_profile import (
    VoiceProfile,
    VoiceProfileResolutionResult,
    VoiceProfileStatus,
    normalize_voice_profile_id,
)


class VoiceProfileRegistryService:
    """
    Provider-independent registry for reusable voice profiles.
    """

    DEFAULT_PROFILE_ID = "voice.neutral_narrator"

    def __init__(
        self,
        *,
        profiles: list[VoiceProfile] | None = None,
    ) -> None:
        self._profiles: dict[str, VoiceProfile] = {}

        if profiles:
            for profile in profiles:
                self.register(profile)

    # --------------------------------------------------
    # CRUD
    # --------------------------------------------------

    def register(
        self,
        profile: VoiceProfile,
        *,
        replace: bool = False,
    ) -> VoiceProfile:

        profile_id = profile.profile_id

        if profile_id in self._profiles and not replace:
            raise ValueError(f"Voice profile already exists: " f"{profile_id}")

        self._profiles[profile_id] = deepcopy(profile)

        return self._profiles[profile_id]

    def unregister(
        self,
        profile_id: str,
    ) -> VoiceProfile:

        if profile_id == self.DEFAULT_PROFILE_ID:
            raise ValueError("Default voice profile " "cannot be removed.")

        try:
            return self._profiles.pop(profile_id)

        except KeyError as exc:
            raise KeyError(f"Unknown voice profile: " f"{profile_id}") from exc

    def get(
        self,
        profile_id: str,
    ) -> VoiceProfile:

        try:
            return self._profiles[profile_id]

        except KeyError as exc:
            raise KeyError(f"Unknown voice profile: " f"{profile_id}") from exc

    def contains(
        self,
        profile_id: str,
    ) -> bool:

        return profile_id in self._profiles

    def list_all(
        self,
        *,
        active_only: bool = False,
    ) -> list[VoiceProfile]:

        profiles = list(self._profiles.values())

        if active_only:
            profiles = [profile for profile in profiles if profile.usable]

        return sorted(
            profiles,
            key=lambda profile: profile.profile_id,
        )

    # --------------------------------------------------
    # Resolution
    # --------------------------------------------------

    def resolve(
        self,
        profile_id: str,
        *,
        allow_fallback: bool = True,
    ) -> VoiceProfileResolutionResult:
        """
        Resolve a requested voice profile.

        Active exact matches are preferred. Unknown, disabled,
        or deprecated profiles may use an active fallback.
        """

        normalized_id = normalize_voice_profile_id(profile_id)

        exact_profile = self._profiles.get(normalized_id)

        if exact_profile is not None and exact_profile.usable:
            return VoiceProfileResolutionResult(
                requested_profile_id=(normalized_id),
                resolved_profile_id=(exact_profile.profile_id),
                profile=deepcopy(exact_profile),
                found_exact_match=True,
                used_fallback=False,
            )

        warning = self._build_warning(
            profile_id=normalized_id,
            profile=exact_profile,
        )

        if not allow_fallback:
            return VoiceProfileResolutionResult(
                requested_profile_id=(normalized_id),
                found_exact_match=False,
                used_fallback=False,
                warning=warning,
            )

        fallback_id = (
            exact_profile.fallback_profile_id
            if (
                exact_profile is not None
                and (exact_profile.fallback_profile_id is not None)
            )
            else self.DEFAULT_PROFILE_ID
        )

        fallback_profile = self._profiles.get(fallback_id)

        if fallback_profile is None or not fallback_profile.usable:
            return VoiceProfileResolutionResult(
                requested_profile_id=(normalized_id),
                found_exact_match=False,
                used_fallback=False,
                warning=(
                    warning + " No usable fallback voice " "profile is registered."
                ),
            )

        return VoiceProfileResolutionResult(
            requested_profile_id=(normalized_id),
            resolved_profile_id=(fallback_profile.profile_id),
            profile=deepcopy(fallback_profile),
            found_exact_match=False,
            used_fallback=True,
            warning=(
                warning + " Safe fallback "
                f"'{fallback_profile.profile_id}' "
                "was selected."
            ),
        )

    @staticmethod
    def _build_warning(
        *,
        profile_id: str,
        profile: VoiceProfile | None,
    ) -> str:
        """Build a voice-profile resolution warning."""

        if profile is None:
            return "Requested voice profile is not " f"registered: {profile_id}."

        if profile.status == VoiceProfileStatus.DISABLED:
            return "Requested voice profile is disabled: " f"{profile_id}."

        if profile.status == VoiceProfileStatus.DEPRECATED:
            return "Requested voice profile is deprecated: " f"{profile_id}."

        return "Requested voice profile is not active: " f"{profile_id}."

    # --------------------------------------------------
    # Defaults
    # --------------------------------------------------

    @classmethod
    def with_default_profiles(
        cls,
    ) -> VoiceProfileRegistryService:
        """Create a registry with built-in voice profiles."""

        return cls(
            profiles=[
                VoiceProfile(
                    profile_id=("voice.neutral_narrator"),
                    display_name=("Neutral Narrator"),
                    description=("Safe, clear and balanced " "general narration."),
                    fallback_profile_id=None,
                    emotion=VoiceEmotion.NEUTRAL,
                    pace=VoicePace.MODERATE,
                    energy=VoiceEnergy.MEDIUM,
                    pitch_style=(VoicePitchStyle.NATURAL),
                    pause_style=(VoicePauseStyle.NATURAL),
                    emphasis_style=(VoiceEmphasisStyle.BALANCED),
                    default_speed=1.0,
                    default_pitch_adjustment=0.0,
                    default_volume_gain_db=0.0,
                    default_stability=0.5,
                    default_similarity_boost=0.75,
                    default_style_strength=0.0,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                        },
                        "openai": {
                            "model": ("gpt-4o-mini-tts"),
                        },
                    },
                    tags=[
                        "safe",
                        "default",
                        "neutral",
                    ],
                ),
                VoiceProfile(
                    profile_id=("voice.horror_whisper"),
                    display_name=("Horror Whisper"),
                    description=("Deep, slow and suspenseful " "horror narration."),
                    emotion=(VoiceEmotion.SUSPENSEFUL),
                    pace=VoicePace.SLOW,
                    energy=VoiceEnergy.LOW,
                    pitch_style=(VoicePitchStyle.DEEP),
                    pause_style=(VoicePauseStyle.DRAMATIC),
                    emphasis_style=(VoiceEmphasisStyle.SELECTIVE),
                    default_speed=0.9,
                    default_pitch_adjustment=-2.0,
                    default_volume_gain_db=0.5,
                    default_stability=0.7,
                    default_similarity_boost=0.8,
                    default_style_strength=0.45,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                            "recommended_voice_tags": [
                                "deep",
                                "dark",
                                "whisper",
                            ],
                        },
                    },
                    tags=[
                        "horror",
                        "dark",
                        "whisper",
                    ],
                ),
                VoiceProfile(
                    profile_id=("voice.documentary_authoritative"),
                    display_name=("Documentary Authoritative"),
                    description=(
                        "Clear, serious and authoritative " "documentary narration."
                    ),
                    emotion=(VoiceEmotion.AUTHORITATIVE),
                    pace=VoicePace.MODERATE,
                    energy=VoiceEnergy.MEDIUM,
                    pitch_style=(VoicePitchStyle.NATURAL),
                    pause_style=(VoicePauseStyle.NATURAL),
                    emphasis_style=(VoiceEmphasisStyle.BALANCED),
                    default_speed=1.0,
                    default_pitch_adjustment=0.0,
                    default_volume_gain_db=0.0,
                    default_stability=0.75,
                    default_similarity_boost=0.8,
                    default_style_strength=0.15,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                            "recommended_voice_tags": [
                                "authoritative",
                                "clear",
                                "serious",
                            ],
                        },
                    },
                    tags=[
                        "documentary",
                        "authoritative",
                        "educational",
                    ],
                ),
                VoiceProfile(
                    profile_id=("voice.history_narrator"),
                    display_name=("History Narrator"),
                    description=(
                        "Serious, cinematic and measured " "historical narration."
                    ),
                    emotion=VoiceEmotion.SERIOUS,
                    pace=VoicePace.MODERATE,
                    energy=VoiceEnergy.MEDIUM,
                    pitch_style=(VoicePitchStyle.DEEP),
                    pause_style=(VoicePauseStyle.CINEMATIC),
                    emphasis_style=(VoiceEmphasisStyle.SELECTIVE),
                    default_speed=0.98,
                    default_pitch_adjustment=-1.0,
                    default_volume_gain_db=0.0,
                    default_stability=0.72,
                    default_similarity_boost=0.8,
                    default_style_strength=0.25,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                            "recommended_voice_tags": [
                                "historic",
                                "deep",
                                "cinematic",
                            ],
                        },
                    },
                    tags=[
                        "history",
                        "cinematic",
                        "serious",
                    ],
                ),
                VoiceProfile(
                    profile_id=("voice.travel_energetic"),
                    display_name=("Travel Energetic"),
                    description=("Bright, fast and enthusiastic " "travel narration."),
                    emotion=VoiceEmotion.EXCITED,
                    pace=VoicePace.FAST,
                    energy=VoiceEnergy.HIGH,
                    pitch_style=(VoicePitchStyle.BRIGHT),
                    pause_style=(VoicePauseStyle.MINIMAL),
                    emphasis_style=(VoiceEmphasisStyle.BALANCED),
                    default_speed=1.08,
                    default_pitch_adjustment=1.0,
                    default_volume_gain_db=0.5,
                    default_stability=0.55,
                    default_similarity_boost=0.75,
                    default_style_strength=0.35,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                            "recommended_voice_tags": [
                                "bright",
                                "energetic",
                                "friendly",
                            ],
                        },
                    },
                    tags=[
                        "travel",
                        "energetic",
                        "bright",
                    ],
                ),
                VoiceProfile(
                    profile_id=("voice.top10_energetic"),
                    display_name=("Top 10 Energetic"),
                    description=(
                        "Fast, high-energy countdown " "and ranked-list narration."
                    ),
                    emotion=VoiceEmotion.EXCITED,
                    pace=VoicePace.VERY_FAST,
                    energy=VoiceEnergy.VERY_HIGH,
                    pitch_style=(VoicePitchStyle.BRIGHT),
                    pause_style=(VoicePauseStyle.MINIMAL),
                    emphasis_style=(VoiceEmphasisStyle.RANK_NUMBERS),
                    default_speed=1.15,
                    default_pitch_adjustment=1.5,
                    default_volume_gain_db=0.8,
                    default_stability=0.5,
                    default_similarity_boost=0.75,
                    default_style_strength=0.5,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                            "recommended_voice_tags": [
                                "energetic",
                                "countdown",
                                "excited",
                            ],
                        },
                    },
                    tags=[
                        "top10",
                        "countdown",
                        "energetic",
                    ],
                ),
                VoiceProfile(
                    profile_id=("voice.warm_storyteller"),
                    display_name=("Warm Storyteller"),
                    description=(
                        "Warm, emotional and expressive " "character-led narration."
                    ),
                    emotion=VoiceEmotion.WARM,
                    pace=VoicePace.DYNAMIC,
                    energy=VoiceEnergy.MEDIUM,
                    pitch_style=(VoicePitchStyle.NATURAL),
                    pause_style=(VoicePauseStyle.DRAMATIC),
                    emphasis_style=(VoiceEmphasisStyle.EMOTIONAL),
                    default_speed=0.98,
                    default_pitch_adjustment=0.0,
                    default_volume_gain_db=0.0,
                    default_stability=0.6,
                    default_similarity_boost=0.8,
                    default_style_strength=0.4,
                    default_speaker_boost=True,
                    provider_mappings={
                        "elevenlabs": {
                            "model_id": ("eleven_multilingual_v2"),
                            "recommended_voice_tags": [
                                "warm",
                                "emotional",
                                "storyteller",
                            ],
                        },
                    },
                    tags=[
                        "storytelling",
                        "warm",
                        "emotional",
                    ],
                ),
            ]
        )
