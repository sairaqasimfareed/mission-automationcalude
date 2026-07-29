from pydantic import ValidationError

from src.models.specification_enums import (
    NarrationStyle,
    SubtitleMode,
    VoiceGender,
    VoiceStrategy,
)
from src.models.voice_settings import VoiceSettings

manual_settings = VoiceSettings(
    strategy=VoiceStrategy.MANUAL_UPLOAD,
    language=" English ",
    preferred_gender=VoiceGender.NEUTRAL,
    narration_style=NarrationStyle.DOCUMENTARY,
    manual_voice_file=("assets/audio/manual/narration.wav"),
    subtitle_mode=SubtitleMode.AUTO_GENERATE,
)

print("Manual strategy:", manual_settings.strategy)
print("Language:", manual_settings.language)
print("Narration:", manual_settings.narration_style)
print("Manual file:", manual_settings.manual_voice_file)

assert manual_settings.language == "English"
assert manual_settings.strategy == VoiceStrategy.MANUAL_UPLOAD
assert manual_settings.manual_voice_file is not None


auto_settings = VoiceSettings(
    strategy=VoiceStrategy.AUTO_GENERATE,
    language="English",
    preferred_gender=VoiceGender.MALE,
    narration_style=NarrationStyle.STORYTELLING,
    speaking_rate=1.05,
    pitch=-1.0,
    volume_gain_db=1.5,
    preferred_provider_profile_id="voice-profile-001",
    preferred_model="multilingual-v2",
    preferred_voice_id="narrator-001",
)

print("Auto strategy:", auto_settings.strategy)
print(
    "Provider profile:",
    auto_settings.preferred_provider_profile_id,
)
print("Speaking rate:", auto_settings.speaking_rate)

assert auto_settings.strategy == VoiceStrategy.AUTO_GENERATE
assert auto_settings.preferred_provider_profile_id == "voice-profile-001"
assert auto_settings.speaking_rate == 1.05


try:
    VoiceSettings(
        strategy=VoiceStrategy.MANUAL_UPLOAD,
        preferred_provider_profile_id="voice-provider",
    )
except ValidationError:
    print("Provider with manual strategy successfully blocked.")
else:
    raise AssertionError("Manual strategy must not use an auto provider.")


try:
    VoiceSettings(
        strategy=VoiceStrategy.AUTO_GENERATE,
        manual_voice_file="assets/audio/manual.wav",
    )
except ValidationError:
    print("Manual file with auto strategy successfully blocked.")
else:
    raise AssertionError("Auto strategy must not include a manual file.")


try:
    VoiceSettings(
        speaking_rate=2.5,
    )
except ValidationError:
    print("Invalid speaking rate successfully blocked.")
else:
    raise AssertionError("Speaking rate above the limit should fail.")


try:
    VoiceSettings(
        language=" ",
    )
except ValidationError:
    print("Empty voice language successfully blocked.")
else:
    raise AssertionError("Empty voice language should fail.")


serialized = auto_settings.model_dump_json()
restored = VoiceSettings.model_validate_json(serialized)

assert restored == auto_settings
assert restored.schema_version == "1.0"

print("Voice Settings tests completed successfully.")
