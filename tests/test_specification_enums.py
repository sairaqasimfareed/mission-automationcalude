from src.models.specification_enums import (
    AspectRatio,
    FrameRate,
    QualityMode,
    VideoResolution,
    VideoType,
)


print("Video type:", VideoType.DOCUMENTARY)
print("Resolution:", VideoResolution.FULL_HD)
print("Aspect ratio:", AspectRatio.LANDSCAPE)
print("Frame rate:", FrameRate.FPS_30)
print("Quality:", QualityMode.PREMIUM)

assert VideoType.DOCUMENTARY.value == "documentary"
assert VideoType.TOP_10.value == "top_10"

assert VideoResolution.FULL_HD.value == "1920x1080"
assert VideoResolution.UHD_4K.value == "3840x2160"

assert AspectRatio.LANDSCAPE.value == "16:9"
assert AspectRatio.PORTRAIT.value == "9:16"

assert FrameRate.FPS_24.value == 24
assert FrameRate.FPS_30.value == 30
assert FrameRate.FPS_60.value == 60

assert QualityMode.PREMIUM.value == "premium"

print("Specification Enums tests completed successfully.")