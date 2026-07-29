from pydantic import ValidationError

from src.models.advanced_settings import AdvancedSettings

settings = AdvancedSettings()

print("Dry run:", settings.dry_run)
print("Retry failed stages:", settings.retry_failed_stages)
print("Maximum retries:", settings.maximum_stage_retries)
print("Skip upload:", settings.skip_upload)
print("Save state:", settings.save_pipeline_state)

assert settings.dry_run is True
assert settings.retry_failed_stages is True
assert settings.maximum_stage_retries == 3
assert settings.skip_completed_stages is True
assert settings.skip_upload is True
assert settings.require_upload_confirmation is True
assert settings.save_pipeline_state is True
assert settings.enable_cost_tracking is True


production_settings = AdvancedSettings(
    dry_run=False,
    skip_upload=False,
    require_upload_confirmation=True,
)

assert production_settings.dry_run is False
assert production_settings.skip_upload is False


no_retry_settings = AdvancedSettings(
    retry_failed_stages=False,
    maximum_stage_retries=0,
)

assert no_retry_settings.maximum_stage_retries == 0


partial_output_settings = AdvancedSettings(
    stop_on_stage_failure=False,
    allow_partial_output=True,
)

assert partial_output_settings.allow_partial_output is True


try:
    AdvancedSettings(
        retry_failed_stages=False,
        maximum_stage_retries=3,
    )
except ValidationError:
    print("Retry count with disabled retry successfully blocked.")
else:
    raise AssertionError("Disabled retry must require zero retries.")


try:
    AdvancedSettings(
        dry_run=True,
        skip_upload=False,
    )
except ValidationError:
    print("Dry-run upload successfully blocked.")
else:
    raise AssertionError("Dry-run mode must skip upload.")


try:
    AdvancedSettings(
        dry_run=False,
        skip_upload=False,
        require_upload_confirmation=False,
    )
except ValidationError:
    print("Upload without confirmation successfully blocked.")
else:
    raise AssertionError("Active upload must require confirmation.")


try:
    AdvancedSettings(
        stop_on_stage_failure=True,
        allow_partial_output=True,
    )
except ValidationError:
    print("Contradictory partial output successfully blocked.")
else:
    raise AssertionError("Partial output cannot stop on first failure.")


serialized = settings.model_dump_json()
restored = AdvancedSettings.model_validate_json(serialized)

assert restored == settings
assert restored.schema_version == "1.0"

print("Advanced Settings tests completed successfully.")
