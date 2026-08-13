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
