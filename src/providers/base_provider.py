from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """
    Base class for every external provider.

    Examples:

    - OpenAI
    - Anthropic
    - Google Veo
    - ElevenLabs
    - YouTube
    - Facebook
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""

    @abstractmethod
    def health_check(self) -> bool:
        """
        Returns True if the provider is available.
        """