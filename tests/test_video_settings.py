from pydantic import ValidationError

from src.models.specification_enums import (
    AspectRatio,
    FrameRate,
    QualityMode,
    VideoResolution,
)
from src.models.video_settings import VideoSettings


settings = VideoSettings(
    resolution=VideoResolution.FULL_HD,
    aspect_ratio=AspectRatio.LANDSCAPE,
    frame_rate=FrameRate.FPS_30,
    quality_mode=QualityMode.PREMIUM,
    hdr_enabled=False,
    captions_enabled=True,
)

print("Resolution:", settings.resolution)
print("Aspect ratio:", settings.aspect_ratio)
print("Frame rate:", settings.frame_rate)
print("Quality:", settings.quality_mode)
print("Width:", settings.width)
print("Height:", settings.height)

assert settings.width == 1920
assert settings.height == 1080
assert settings.frames_per_second == 30
assert settings.captions_enabled is True


default_settings = VideoSettings()

assert default_settings.resolution == VideoResolution.FULL_HD
assert default_settings.aspect_ratio == AspectRatio.LANDSCAPE
assert default_settings.frame_rate == FrameRate.FPS_30
assert default_settings.quality_mode == QualityMode.PREMIUM


try:
    VideoSettings(
        resolution=VideoResolution.UHD_4K,
        aspect_ratio=AspectRatio.PORTRAIT,
    )
except ValidationError:
    print("Invalid portrait 4K preset successfully blocked.")
else:
    raise AssertionError(
        "Landscape 4K preset should not be accepted for portrait output."
    )


try:
    VideoSettings(
        quality_mode=QualityMode.DRAFT,
        hdr_enabled=True,
    )
except ValidationError:
    print("Draft HDR configuration successfully blocked.")
else:
    raise AssertionError(
        "HDR should not be accepted in Draft mode."
    )


serialized = settings.model_dump_json()
restored = VideoSettings.model_validate_json(serialized)

assert restored == settings
assert restored.schema_version == "1.0"

print("Video Settings tests completed successfully.")