from __future__ import annotations

from abc import abstractmethod

from src.providers.base_provider import BaseProvider


class MusicProvider(BaseProvider):
    """
    Base interface for all background-music sourcing providers.

    library_query mirrors the same convention as visual stock search
    (Scene.stock_query): a free-text description a real provider (a
    licensed music library search, or a generative music service like
    Suno or Mubert) can act on, rather than a structured request.

    Examples:
    - A licensed stock-music library search
    - A generative music service
    """

    @abstractmethod
    def generate_music(
        self,
        *,
        library_query: str,
        duration_seconds: float,
    ) -> str:
        """
        Produce one background-music track.

        Returns:
            Path to the produced audio file.
        """

    def generate_composed_music(
        self,
        *,
        prompt: str,
        duration_seconds: float,
    ) -> str:
        """
        Compose ONE track of the full requested length from a description of how it
        should move (a continuous track for a whole video).

        Optional: a provider that can only make short clips (or only searches a library)
        leaves this as it is, and the caller falls back to short pieces.

        Returns:
            Path to the produced audio file.
        """

        raise NotImplementedError(
            f"{self.provider_name} cannot compose a full-length music track."
        )
