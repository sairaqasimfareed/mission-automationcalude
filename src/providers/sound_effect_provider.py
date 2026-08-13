from __future__ import annotations

from abc import abstractmethod

from src.providers.base_provider import BaseProvider


class SoundEffectProvider(BaseProvider):
    """
    Base interface for all sound-effect sourcing providers.

    library_query mirrors MusicProvider's convention: free-text a real
    provider (a licensed SFX library search, or a generative audio
    service) can act on.

    Examples:
    - A licensed stock sound-effect library search
    - A generative audio service
    """

    @abstractmethod
    def generate_sound_effect(
        self,
        *,
        library_query: str,
    ) -> str:
        """
        Produce one short sound-effect clip.

        Returns:
            Path to the produced audio file.
        """
