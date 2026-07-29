from __future__ import annotations

from abc import abstractmethod

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
