from pydantic import ValidationError

from src.models.specification_enums import VisualStrategy
from src.models.visual_settings import VisualSettings


settings = VisualSettings()

print("Strategy:", settings.strategy)
print(
    "Scene override:",
    settings.allow_scene_strategy_override,
)
print(
    "Default clip duration:",
    settings.default_clip_duration_seconds,
)
print(
    "Default transition:",
    settings.default_transition_duration_seconds,
)
print(
    "AI video enabled:",
    settings.allow_ai_video_generation,
)

assert settings.strategy == VisualStrategy.HYBRID
assert settings.allow_scene_strategy_override is True

assert settings.prefer_local_assets is True
assert settings.reuse_existing_assets is True

assert settings.allow_stock_search is True
assert settings.require_user_stock_approval is True

assert settings.allow_manual_upload is True
assert settings.allow_image_to_video is True
assert settings.allow_ai_video_generation is False

assert settings.default_clip_duration_seconds == 8
assert settings.default_transition_duration_seconds == 0.5


local_settings = VisualSettings(
    strategy=VisualStrategy.LOCAL_LIBRARY,
    prefer_local_assets=True,
)

assert (
    local_settings.strategy
    == VisualStrategy.LOCAL_LIBRARY
)


stock_settings = VisualSettings(
    strategy=VisualStrategy.STOCK_FOOTAGE,
    allow_stock_search=True,
)

assert (
    stock_settings.strategy
    == VisualStrategy.STOCK_FOOTAGE
)


try:
    VisualSettings(
        strategy=VisualStrategy.STOCK_FOOTAGE,
        allow_stock_search=False,
    )
except ValidationError:
    print("Disabled stock strategy successfully blocked.")
else:
    raise AssertionError(
        "Stock strategy without stock search should fail."
    )


try:
    VisualSettings(
        strategy=VisualStrategy.AI_VIDEO,
        allow_ai_video_generation=False,
    )
except ValidationError:
    print("Disabled AI video strategy successfully blocked.")
else:
    raise AssertionError(
        "AI video strategy should remain blocked "
        "when generation is disabled."
    )


try:
    VisualSettings(
        strategy=VisualStrategy.HYBRID,
        prefer_local_assets=False,
        allow_stock_search=False,
        allow_manual_upload=False,
        allow_image_to_video=False,
        allow_ai_video_generation=False,
    )
except ValidationError:
    print("Empty hybrid strategy successfully blocked.")
else:
    raise AssertionError(
        "Hybrid strategy requires an enabled source."
    )


try:
    VisualSettings(
        default_clip_duration_seconds=8,
        default_transition_duration_seconds=8,
    )
except ValidationError:
    print(
        "Invalid transition duration successfully blocked."
    )
else:
    raise AssertionError(
        "Transition duration must be shorter "
        "than clip duration."
    )


serialized = settings.model_dump_json()
restored = VisualSettings.model_validate_json(
    serialized
)

assert restored == settings
assert restored.schema_version == "1.0"

print("Visual Settings tests completed successfully.")