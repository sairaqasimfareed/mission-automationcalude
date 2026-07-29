from pydantic import ValidationError

from src.models.music_settings import MusicSettings
from src.models.specification_enums import (
    MusicMood,
    MusicStrategy,
)


settings = MusicSettings()

print("Strategy:", settings.strategy)
print("Mood:", settings.mood)
print("Volume:", settings.volume)

assert settings.strategy == MusicStrategy.AUTO_GENERATE
assert settings.mood == MusicMood.CINEMATIC
assert settings.loop_music
assert settings.normalize_audio
assert settings.duck_under_voice


manual = MusicSettings(
    strategy=MusicStrategy.MANUAL_UPLOAD,
    manual_music_file="assets/music/theme.mp3",
)

assert manual.manual_music_file is not None


none_music = MusicSettings(
    strategy=MusicStrategy.NONE,
    volume=0.0,
)

assert none_music.strategy == MusicStrategy.NONE


try:
    MusicSettings(
        strategy=MusicStrategy.NONE,
        volume=0.5,
    )
except ValidationError:
    print("NONE strategy validation passed.")
else:
    raise AssertionError


try:
    MusicSettings(
        strategy=MusicStrategy.AUTO_GENERATE,
        manual_music_file="music.mp3",
    )
except ValidationError:
    print("AUTO strategy validation passed.")
else:
    raise AssertionError


serialized = settings.model_dump_json()

restored = MusicSettings.model_validate_json(
    serialized
)

assert restored == settings

print("Music Settings tests completed successfully.")