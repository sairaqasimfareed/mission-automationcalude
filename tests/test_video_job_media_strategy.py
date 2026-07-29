from pydantic import ValidationError

from src.models.enums import Platform, ProductionMode
from src.models.media_strategy import (
    SceneSourceType,
    VisualStrategy,
    VoiceStatus,
    VoiceStrategy,
)
from src.models.video_job import VideoJob


job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery and Hidden Places",
    topic="Top 10 Hidden Underground Cities",
    platform=Platform.YOUTUBE,
    production_mode=ProductionMode.PREMIUM,
    visual_strategy=VisualStrategy.HYBRID,
    default_visual_source=SceneSourceType.STOCK_FOOTAGE,
    maximum_visual_budget=3.0,
    voice_strategy=VoiceStrategy.MANUAL_UPLOAD,
    voice_status=VoiceStatus.WAITING_FOR_UPLOAD,
)

print("Visual strategy:", job.visual_strategy)
print("Default visual source:", job.default_visual_source)
print("Maximum visual budget:", job.maximum_visual_budget)
print("Voice strategy:", job.voice_strategy)
print("Voice status:", job.voice_status)

assert job.visual_strategy == VisualStrategy.HYBRID
assert job.default_visual_source == SceneSourceType.STOCK_FOOTAGE
assert job.maximum_visual_budget == 3.0
assert job.voice_strategy == VoiceStrategy.MANUAL_UPLOAD
assert job.voice_status == VoiceStatus.WAITING_FOR_UPLOAD


try:
    VideoJob(
        project_name="Mission Automation",
        channel_name="Beyond the Ninth",
        niche="Mystery and Hidden Places",
        topic="Invalid Manual Voice",
        voice_strategy=VoiceStrategy.MANUAL_UPLOAD,
        voice_status=VoiceStatus.READY,
        voice_file=None,
    )
except ValidationError:
    print("Manual READY voice without file successfully blocked.")
else:
    raise AssertionError(
        "Manual READY voice without a file should be blocked."
    )


ready_voice_job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery and Hidden Places",
    topic="Valid Manual Voice",
    voice_strategy=VoiceStrategy.MANUAL_UPLOAD,
    voice_status=VoiceStatus.READY,
    voice_file="assets/audio/manual_voiceover.wav",
)

print("Ready voice file:", ready_voice_job.voice_file)

assert ready_voice_job.voice_status == VoiceStatus.READY
assert ready_voice_job.voice_file == (
    "assets/audio/manual_voiceover.wav"
)

print("VideoJob Media Strategy tests completed successfully.")