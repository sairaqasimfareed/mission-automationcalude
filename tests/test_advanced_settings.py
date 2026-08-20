from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.advanced_settings import AdvancedSettings, ExecutionMode
from src.models.provider_profile import ProviderCategory


def test_defaults_are_conservative() -> None:
    settings = AdvancedSettings()

    assert settings.dry_run is True
    assert settings.execution_mode == ExecutionMode.DRY_RUN
    assert settings.retry_failed_stages is True
    assert settings.maximum_stage_retries == 3
    assert settings.skip_completed_stages is True
    assert settings.skip_upload is True
    assert settings.require_upload_confirmation is True
    assert settings.save_pipeline_state is True
    assert settings.enable_cost_tracking is True


def test_setting_dry_run_false_derives_live_execution_mode() -> None:
    settings = AdvancedSettings(
        dry_run=False,
        skip_upload=False,
        require_upload_confirmation=True,
    )

    assert settings.dry_run is False
    assert settings.skip_upload is False
    assert settings.execution_mode == ExecutionMode.LIVE


def test_setting_execution_mode_live_derives_dry_run_false() -> None:
    settings = AdvancedSettings(
        execution_mode=ExecutionMode.LIVE,
        skip_upload=False,
        require_upload_confirmation=True,
    )

    assert settings.dry_run is False


def test_setting_execution_mode_dry_run_derives_dry_run_true() -> None:
    settings = AdvancedSettings(execution_mode=ExecutionMode.DRY_RUN)

    assert settings.dry_run is True


def test_consistent_explicit_values_are_accepted() -> None:
    settings = AdvancedSettings(
        execution_mode=ExecutionMode.LIVE,
        dry_run=False,
        skip_upload=False,
        require_upload_confirmation=True,
    )

    assert settings.execution_mode == ExecutionMode.LIVE
    assert settings.dry_run is False


def test_contradictory_explicit_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AdvancedSettings(execution_mode=ExecutionMode.LIVE, dry_run=True)


def test_mixed_execution_mode_does_not_enforce_a_dry_run_match() -> None:
    # MIXED has no boolean equivalent, so dry_run keeps whatever
    # explicit value the caller gave it rather than being validated
    # against execution_mode.
    settings = AdvancedSettings(
        execution_mode=ExecutionMode.MIXED,
        dry_run=False,
        skip_upload=False,
        require_upload_confirmation=True,
    )

    assert settings.execution_mode == ExecutionMode.MIXED
    assert settings.dry_run is False


def test_resolve_execution_mode_falls_back_to_the_global_mode() -> None:
    settings = AdvancedSettings(execution_mode=ExecutionMode.LIVE)

    assert settings.resolve_execution_mode(ProviderCategory.MUSIC) == ExecutionMode.LIVE


def test_resolve_execution_mode_honors_a_per_category_override() -> None:
    settings = AdvancedSettings(
        execution_mode=ExecutionMode.MIXED,
        dry_run=False,
        skip_upload=False,
        require_upload_confirmation=True,
        provider_execution_overrides={ProviderCategory.MUSIC: ExecutionMode.LIVE},
    )

    assert settings.resolve_execution_mode(ProviderCategory.MUSIC) == ExecutionMode.LIVE
    # An unlisted category under MIXED resolves to DRY_RUN, not the
    # literal MIXED value itself - safe by default.
    assert (
        settings.resolve_execution_mode(ProviderCategory.SOUND_EFFECTS)
        == ExecutionMode.DRY_RUN
    )


def test_no_retry_settings_require_zero_retries() -> None:
    settings = AdvancedSettings(retry_failed_stages=False, maximum_stage_retries=0)

    assert settings.maximum_stage_retries == 0


def test_partial_output_requires_no_stop_on_failure() -> None:
    settings = AdvancedSettings(stop_on_stage_failure=False, allow_partial_output=True)

    assert settings.allow_partial_output is True


def test_retry_count_with_disabled_retry_is_blocked() -> None:
    with pytest.raises(ValidationError):
        AdvancedSettings(retry_failed_stages=False, maximum_stage_retries=3)


def test_dry_run_with_upload_enabled_is_blocked() -> None:
    with pytest.raises(ValidationError):
        AdvancedSettings(dry_run=True, skip_upload=False)


def test_upload_without_confirmation_is_blocked() -> None:
    with pytest.raises(ValidationError):
        AdvancedSettings(
            dry_run=False, skip_upload=False, require_upload_confirmation=False
        )


def test_contradictory_partial_output_is_blocked() -> None:
    with pytest.raises(ValidationError):
        AdvancedSettings(stop_on_stage_failure=True, allow_partial_output=True)


def test_round_trips_through_json() -> None:
    settings = AdvancedSettings(
        execution_mode=ExecutionMode.MIXED,
        dry_run=False,
        skip_upload=False,
        require_upload_confirmation=True,
        provider_execution_overrides={ProviderCategory.MUSIC: ExecutionMode.LIVE},
    )

    restored = AdvancedSettings.model_validate_json(settings.model_dump_json())

    assert restored == settings
    assert restored.schema_version == "1.0"
    assert restored.provider_execution_overrides == {
        ProviderCategory.MUSIC: ExecutionMode.LIVE
    }


def test_old_serialized_data_without_execution_mode_still_loads() -> None:
    # Simulates a project file saved before Phase 8 existed - only
    # dry_run was ever written, execution_mode is absent entirely.
    old_json = (
        '{"dry_run": false, "skip_upload": false, "require_upload_confirmation": true}'
    )

    restored = AdvancedSettings.model_validate_json(old_json)

    assert restored.dry_run is False
    assert restored.execution_mode == ExecutionMode.LIVE
