from __future__ import annotations

import json

from src.models.enums import ScriptOrigin
from src.models.video_job import VideoJob


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    base.update(overrides)
    return VideoJob(**base)


def test_provider_preferences_defaults_to_unconfigured() -> None:
    job = _job()

    assert job.provider_preferences.llm.preferred_profile_id is None
    assert job.provider_preferences.reviewer.reviewer_profile_id is None


def test_script_origin_defaults_to_internal() -> None:
    job = _job()

    assert job.script_origin == ScriptOrigin.INTERNAL


def test_old_video_job_json_without_the_new_fields_loads_with_defaults() -> None:
    """
    A project file saved before provider_preferences/script_origin
    existed has neither key at all - Pydantic's defaults must absorb
    that silently, the same proven pattern every other VideoJob field
    addition this session has relied on.
    """

    job = _job()
    old_shape = json.loads(job.model_dump_json())
    del old_shape["provider_preferences"]
    del old_shape["script_origin"]

    reloaded = VideoJob.model_validate(old_shape)

    assert reloaded.provider_preferences.llm.preferred_profile_id is None
    assert reloaded.provider_preferences.reviewer.reviewer_profile_id is None
    assert reloaded.script_origin == ScriptOrigin.INTERNAL


def test_video_job_round_trips_populated_provider_preferences() -> None:
    job = _job()
    job.provider_preferences.llm.preferred_profile_id = "openai-primary"
    job.provider_preferences.llm.fallback_profile_ids = ["anthropic-fallback"]
    job.provider_preferences.reviewer.reviewer_profile_id = "anthropic-reviewer"
    job.script_origin = ScriptOrigin.EXTERNAL

    reloaded = VideoJob.model_validate_json(job.model_dump_json())

    assert reloaded.provider_preferences.llm.preferred_profile_id == "openai-primary"
    assert reloaded.provider_preferences.llm.fallback_profile_ids == [
        "anthropic-fallback"
    ]
    assert reloaded.provider_preferences.reviewer.reviewer_profile_id == (
        "anthropic-reviewer"
    )
    assert reloaded.script_origin == ScriptOrigin.EXTERNAL
