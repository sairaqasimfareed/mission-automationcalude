from __future__ import annotations

from src.models.scene import Scene
from src.models.voice_directives import (
    SceneVoiceDirectives,
    VoiceDirectiveSource,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


class GenreVoiceDirectiveGenerationService:
    """
    Generate provider-independent voice directives for planned scenes.

    Genre profiles select the requested reusable voice profile.
    The resolved VoiceProfile supplies the canonical typed voice
    parameters used by SceneVoiceDirectives.

    Provider-specific execution remains owned by the existing voice
    resolution and generation services.
    """

    def __init__(
        self,
        *,
        genre_registry: GenreProfileRegistryService,
        voice_profile_registry: VoiceProfileRegistryService,
    ) -> None:
        self._genre_registry = genre_registry
        self._voice_profile_registry = voice_profile_registry

    @property
    def genre_registry(
        self,
    ) -> GenreProfileRegistryService:
        return self._genre_registry

    @property
    def voice_profile_registry(
        self,
    ) -> VoiceProfileRegistryService:
        return self._voice_profile_registry

    def generate(
        self,
        *,
        scene: Scene,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
    ) -> SceneVoiceDirectives:
        """
        Generate voice directives for one scene.

        Unknown or unavailable genres use the existing genre-registry
        fallback behavior. Voice-profile fallback remains delegated to
        VoiceProfileRegistryService.
        """

        genre_resolution = self._genre_registry.resolve(
            genre_id,
            allow_fallback=True,
        )

        if (
            not genre_resolution.is_resolved
            or genre_resolution.profile is None
            or genre_resolution.resolved_genre_id is None
        ):
            raise ValueError("Genre profile could not be resolved: " f"{genre_id}")

        genre_profile = genre_resolution.profile

        requested_voice_profile_id = genre_profile.voice.voice_profile_id

        voice_resolution = self._voice_profile_registry.resolve(
            requested_voice_profile_id,
            allow_fallback=True,
        )

        if (
            not voice_resolution.is_resolved
            or voice_resolution.profile is None
            or voice_resolution.resolved_profile_id is None
        ):
            raise ValueError(
                "Voice profile could not be resolved "
                "for genre "
                f"'{genre_resolution.resolved_genre_id}': "
                f"{requested_voice_profile_id}"
            )

        voice_profile = voice_resolution.profile

        warnings: list[str] = []

        if genre_resolution.warning:
            warnings.append(genre_resolution.warning)

        if voice_resolution.warning and voice_resolution.warning not in warnings:
            warnings.append(voice_resolution.warning)

        return SceneVoiceDirectives(
            scene_number=scene.scene_number,
            voice_profile_id=(requested_voice_profile_id),
            fallback_voice_profile_id=(voice_profile.fallback_profile_id),
            language=language,
            language_code=language_code,
            emotion=voice_profile.emotion,
            pace=voice_profile.pace,
            energy=voice_profile.energy,
            pitch_style=(voice_profile.pitch_style),
            pause_style=(voice_profile.pause_style),
            emphasis_style=(voice_profile.emphasis_style),
            speed=voice_profile.default_speed,
            pitch_adjustment=(voice_profile.default_pitch_adjustment),
            volume_gain_db=(voice_profile.default_volume_gain_db),
            stability=(voice_profile.default_stability),
            similarity_boost=(voice_profile.default_similarity_boost),
            style_strength=(voice_profile.default_style_strength),
            speaker_boost=(voice_profile.default_speaker_boost),
            source=(VoiceDirectiveSource.GENRE_PROFILE),
            warnings=warnings,
            metadata={
                "requested_genre_id": (genre_id.strip().lower()),
                "resolved_genre_id": (genre_resolution.resolved_genre_id),
                "genre_fallback_used": (genre_resolution.used_fallback),
                "genre_profile_version": (genre_profile.version),
                "genre_profile_schema_version": (genre_profile.schema_version),
                "requested_voice_profile_id": (requested_voice_profile_id),
                "resolved_voice_profile_id": (voice_resolution.resolved_profile_id),
                "voice_profile_fallback_used": (voice_resolution.used_fallback),
                "voice_profile_version": (voice_profile.version),
                "voice_profile_schema_version": (voice_profile.schema_version),
                "scene_title": scene.title,
                "scene_duration_seconds": (scene.estimated_duration_seconds),
                "genre_voice_defaults": (
                    genre_profile.voice.model_dump(
                        mode="json",
                    )
                ),
            },
        )

    def generate_many(
        self,
        *,
        scenes: list[Scene],
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
    ) -> list[SceneVoiceDirectives]:
        """
        Generate ordered voice directives for multiple scenes.

        Duplicate scene numbers are rejected before directive creation.
        """

        scene_numbers = [scene.scene_number for scene in scenes]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Duplicate scene numbers cannot be used "
                "for voice directive generation."
            )

        directives = [
            self.generate(
                scene=scene,
                genre_id=genre_id,
                language=language,
                language_code=language_code,
            )
            for scene in scenes
        ]

        return sorted(
            directives,
            key=lambda item: item.scene_number,
        )
