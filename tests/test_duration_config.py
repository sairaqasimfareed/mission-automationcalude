from pydantic import ValidationError

from src.models.duration_config import (
    DurationConfig,
    DurationMode,
)

exact_config = DurationConfig(
    mode=DurationMode.EXACT,
    target_duration_seconds=600,
    tolerance_seconds=15,
)

print("Exact mode:", exact_config.mode)
print(
    "Preferred duration:",
    exact_config.preferred_duration_seconds,
)

assert exact_config.preferred_duration_seconds == 600
assert exact_config.is_within_allowed_duration(590)
assert exact_config.is_within_allowed_duration(615)
assert not exact_config.is_within_allowed_duration(616)


range_config = DurationConfig(
    mode=DurationMode.RANGE,
    minimum_duration_seconds=480,
    maximum_duration_seconds=600,
    tolerance_seconds=10,
)

print("Range mode:", range_config.mode)
print(
    "Preferred duration:",
    range_config.preferred_duration_seconds,
)

assert range_config.preferred_duration_seconds == 540
assert range_config.is_within_allowed_duration(470)
assert range_config.is_within_allowed_duration(610)
assert not range_config.is_within_allowed_duration(611)


try:
    DurationConfig(
        mode=DurationMode.EXACT,
    )
except ValidationError:
    print("Missing exact duration successfully blocked.")
else:
    raise AssertionError("Exact mode without target duration should fail.")


try:
    DurationConfig(
        mode=DurationMode.RANGE,
        minimum_duration_seconds=700,
        maximum_duration_seconds=600,
    )
except ValidationError:
    print("Invalid duration range successfully blocked.")
else:
    raise AssertionError("Minimum duration above maximum should fail.")


try:
    DurationConfig(
        mode=DurationMode.EXACT,
        target_duration_seconds=600,
        minimum_duration_seconds=500,
    )
except ValidationError:
    print("Mixed duration configuration successfully blocked.")
else:
    raise AssertionError("Exact mode must not include range values.")


serialized = exact_config.model_dump_json()
restored = DurationConfig.model_validate_json(serialized)

assert restored == exact_config
assert restored.schema_version == "1.0"

print("Duration Config tests completed successfully.")
