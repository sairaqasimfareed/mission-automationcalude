from __future__ import annotations

from src.providers.sound_effect_provider import SoundEffectProvider


class DryRunSoundEffectProvider(SoundEffectProvider):
    """
    Deterministic sound-effect provider used during dry-run execution.

    Mirrors the role DryRunVoiceProvider/DryRunMusicProvider play: it
    lets a full production runtime be composed and exercised without a
    real SFX library or generation credentials configured.
    """

    @property
    def provider_name(self) -> str:
        return "dry_run"

    def health_check(self) -> bool:
        return True

    def generate_sound_effect(
        self,
        *,
        library_query: str,
    ) -> str:
        slug = "_".join(library_query.strip().lower().split()) or "untitled"

        return f"dry-run://sfx/{slug}.mp3"
