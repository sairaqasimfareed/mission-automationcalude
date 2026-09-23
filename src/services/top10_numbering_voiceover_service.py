from __future__ import annotations

from src.models.voice_directives import SceneVoiceDirectives
from src.models.voice_generation import VoiceGenerationResult
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_generation_service import VoiceGenerationService


class TopTenNumberingVoiceoverService:
    """
    REQ-12 (top10 countdown rank cards): generate one short "Number
    {N}." voiceover line per countdown rank.

    Reuses the exact same real voice-resolution/generation machinery
    real scene narration already goes through -
    VoiceDirectiveResolutionService + VoiceGenerationService - rather
    than a second, parallel voice-generation implementation.
    voice_profile_id is the job's own genre voice profile (matching
    the rest of the video's narration for consistency), passed in by
    the caller rather than hardcoded here - this service has no
    opinion on which genre it's serving.
    """

    def __init__(
        self,
        *,
        voice_directive_resolution_service: VoiceDirectiveResolutionService,
        voice_generation_service: VoiceGenerationService,
    ) -> None:
        self._voice_directive_resolution_service = voice_directive_resolution_service
        self._voice_generation_service = voice_generation_service

    def generate(
        self,
        *,
        rank: int,
        voice_profile_id: str,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        """Generate the "Number {rank}." voiceover line for one card."""

        directives = SceneVoiceDirectives(
            scene_number=rank,
            voice_profile_id=voice_profile_id,
        )

        blueprint = self._voice_directive_resolution_service.resolve(
            directives,
            narration_text=f"Number {rank}.",
            target_provider=provider_name,
        )

        return self._voice_generation_service.generate(
            blueprint,
            provider_name=provider_name,
        )
