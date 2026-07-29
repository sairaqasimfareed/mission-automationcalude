from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
    VisualStrategy,
    VoiceStatus,
    VoiceStrategy,
)

print("Visual strategy:", VisualStrategy.HYBRID)
print("Manual source:", SceneSourceType.MANUAL_UPLOAD)
print("Stock source:", SceneSourceType.STOCK_FOOTAGE)
print("Local source:", SceneSourceType.LOCAL_LIBRARY)
print("Image-to-video source:", SceneSourceType.IMAGE_TO_VIDEO)
print("Reserved AI source:", SceneSourceType.AI_GENERATE)

print("Voice auto:", VoiceStrategy.AUTO_GENERATE)
print("Voice manual:", VoiceStrategy.MANUAL_UPLOAD)

print("Scene ready:", SceneSourceStatus.READY)
print("Voice ready:", VoiceStatus.READY)

assert VisualStrategy.HYBRID.value == "hybrid"
assert SceneSourceType.MANUAL_UPLOAD.value == "manual_upload"
assert SceneSourceType.AI_GENERATE.value == "ai_generate"
assert VoiceStrategy.AUTO_GENERATE.value == "auto_generate"
assert VoiceStrategy.MANUAL_UPLOAD.value == "manual_upload"

print("Media Strategy tests completed successfully.")
