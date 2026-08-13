from __future__ import annotations

from src.providers.dry_run_music_provider import DryRunMusicProvider
from src.providers.dry_run_sound_effect_provider import DryRunSoundEffectProvider

music_provider = DryRunMusicProvider()

assert music_provider.provider_name == "dry_run"
assert music_provider.health_check() is True

music_output = music_provider.generate_music(
    library_query="dark low suspense drone",
    duration_seconds=40.0,
)

print("Music output:", music_output)

assert music_output == "dry-run://music/dark_low_suspense_drone.mp3"
assert music_provider.generate_music(library_query="  ", duration_seconds=1.0) == (
    "dry-run://music/untitled.mp3"
)


sound_effect_provider = DryRunSoundEffectProvider()

assert sound_effect_provider.provider_name == "dry_run"
assert sound_effect_provider.health_check() is True

sfx_output = sound_effect_provider.generate_sound_effect(
    library_query="wooden door slow creak",
)

print("Sound effect output:", sfx_output)

assert sfx_output == "dry-run://sfx/wooden_door_slow_creak.mp3"
assert sound_effect_provider.generate_sound_effect(library_query="  ") == (
    "dry-run://sfx/untitled.mp3"
)


print("Dry-run music/sound-effect provider tests completed successfully.")
