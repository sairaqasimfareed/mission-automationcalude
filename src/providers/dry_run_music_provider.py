from __future__ import annotations

from src.providers.music_provider import MusicProvider


class DryRunMusicProvider(MusicProvider):
    """
    Deterministic music provider used during dry-run execution.

    Mirrors the role DryRunVoiceProvider plays for narration: it lets
    a full production runtime be composed and exercised without a
    real music library or generation credentials configured.
    """

    @property
    def provider_name(self) -> str:
        return "dry_run"

    def health_check(self) -> bool:
        return True

    def generate_music(
        self,
        *,
        library_query: str,
        duration_seconds: float,
    ) -> str:
        slug = "_".join(library_query.strip().lower().split()) or "untitled"

        return f"dry-run://music/{slug}.mp3"
