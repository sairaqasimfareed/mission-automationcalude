from __future__ import annotations

from src.models.provider_preferences import (
    ProviderPreference,
    ProviderPreferences,
    ReviewerConfiguration,
    ReviewerMode,
)


def _voice_preference() -> ProviderPreference:
    return ProviderPreference(
        preferred_profile_id="voice-main",
        fallback_profile_ids=[
            "voice-backup",
            " voice-secondary ",
            "voice-backup",
            "",
        ],
        auto_select=True,
        lock_preferred_provider=False,
    )


def test_fallback_profile_ids_are_cleaned_trimmed_and_deduplicated() -> None:
    preference = _voice_preference()

    assert preference.preferred_profile_id == "voice-main"
    assert preference.fallback_profile_ids == ["voice-backup", "voice-secondary"]


def test_provider_preferences_stores_each_category_independently() -> None:
    voice_preference = _voice_preference()
    preferences = ProviderPreferences(
        voice=voice_preference,
        video=ProviderPreference(
            preferred_profile_id="video-main",
            fallback_profile_ids=["video-backup"],
            auto_select=False,
            lock_preferred_provider=True,
        ),
    )

    assert preferences.voice == voice_preference
    assert preferences.video.preferred_profile_id == "video-main"
    assert preferences.video.auto_select is False
    assert preferences.video.lock_preferred_provider is True

    # Untouched categories keep their own defaults.
    assert preferences.llm.auto_select is True
    assert preferences.image.preferred_profile_id is None


def test_provider_preferences_round_trips_through_json() -> None:
    preferences = ProviderPreferences(voice=_voice_preference())

    restored = ProviderPreferences.model_validate_json(preferences.model_dump_json())

    assert restored == preferences
    assert restored.schema_version == "1.0"


# --- Reviewer configuration (Content Studio Redesign, Phase 2) -------------


def test_reviewer_defaults_to_unconfigured() -> None:
    preferences = ProviderPreferences()

    assert preferences.reviewer.reviewer_profile_id is None
    assert preferences.reviewer.mode == ReviewerMode.ON_DEMAND


def test_reviewer_profile_id_is_trimmed() -> None:
    config = ReviewerConfiguration(reviewer_profile_id="  anthropic-reviewer  ")

    assert config.reviewer_profile_id == "anthropic-reviewer"


def test_reviewer_profile_id_blank_string_becomes_none() -> None:
    config = ReviewerConfiguration(reviewer_profile_id="   ")

    assert config.reviewer_profile_id is None


def test_reviewer_mode_can_be_automatic_at_approval_gates() -> None:
    preferences = ProviderPreferences(
        reviewer=ReviewerConfiguration(
            reviewer_profile_id="anthropic-reviewer",
            mode=ReviewerMode.AUTOMATIC_AT_APPROVAL_GATES,
        )
    )

    assert preferences.reviewer.mode == ReviewerMode.AUTOMATIC_AT_APPROVAL_GATES
    assert preferences.reviewer.reviewer_profile_id == "anthropic-reviewer"


def test_reviewer_round_trips_through_json() -> None:
    preferences = ProviderPreferences(
        reviewer=ReviewerConfiguration(
            reviewer_profile_id="anthropic-reviewer",
            mode=ReviewerMode.AUTOMATIC_AT_APPROVAL_GATES,
        )
    )

    restored = ProviderPreferences.model_validate_json(preferences.model_dump_json())

    assert restored.reviewer.reviewer_profile_id == "anthropic-reviewer"
    assert restored.reviewer.mode == ReviewerMode.AUTOMATIC_AT_APPROVAL_GATES
