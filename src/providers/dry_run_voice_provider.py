from __future__ import annotations

from src.providers.voice_provider import VoiceProvider


class DryRunVoiceProvider(VoiceProvider):
    """
    Deterministic voice provider used during dry-run execution.

    Mirrors the role DryRunProviderAdapter plays for the LLM gateway:
    it lets a full production runtime be composed and exercised without
    a real TTS provider or credentials configured.
    """

    @property
    def provider_name(self) -> str:
        return "dry_run"

    def health_check(self) -> bool:
        return True

    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        return f"dry-run://voice/{voice}.mp3"
