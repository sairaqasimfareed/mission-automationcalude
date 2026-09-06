from __future__ import annotations

from abc import abstractmethod

from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.providers.base_provider import BaseProvider


class VoiceProvider(BaseProvider):
    """
    Base interface for all voice generation providers.

    Examples:
    - ElevenLabs
    - Google TTS
    - Azure Speech
    - OpenAI TTS
    """

    @abstractmethod
    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        """
        Generate voice audio.

        Returns:
            Path to generated audio file.
        """

    def generate_from_blueprint(self, blueprint: ResolvedVoiceBlueprint) -> str:
        """
        Post-Script-Approval Production Plan, Phase 9: "The voice
        provider must consume a translated ResolvedVoiceBlueprint
        rather than only raw narration text."

        Not abstract - a concrete provider gains nothing by being
        forced to override this before it has a real translation to
        offer. The default implementation here is the exact prior
        behavior (`generate_voice` with only text/voice), so every
        existing provider that hasn't been retrofitted (DryRunVoiceProvider)
        keeps working completely unchanged. A provider that has a real
        translator (ElevenLabsVoiceProvider) overrides this instead.
        """

        # Local import to avoid a circular import at module load time -
        # VoiceGenerationService imports providers, so this side of the
        # relationship can only be resolved lazily.
        from src.services.voice_generation_service import VoiceGenerationService

        voice_id = VoiceGenerationService.resolve_provider_voice(blueprint=blueprint)

        return self.generate_voice(text=blueprint.narration_text, voice=voice_id)
