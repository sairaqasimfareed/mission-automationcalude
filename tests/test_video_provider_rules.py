from __future__ import annotations

import pytest

from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.services.video_provider_rules import (
    MUSE_CLIP_DURATION_SECONDS,
    resolve_scene_video_provider,
    rules_for,
)

_FLOW = rules_for(VideoProvider.GOOGLE_FLOW)
_MUSE = rules_for(VideoProvider.MUSE)


def _job(provider: VideoProvider = VideoProvider.GOOGLE_FLOW) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
    )
    job.video_provider = provider

    return job


def _scene(preferred_profile_id: str | None = None) -> Scene:
    scene = Scene(
        scene_number=1,
        title="Scene",
        narration="Narration.",
        visual_prompt="Visual.",
        estimated_duration_seconds=8,
    )
    scene.preferred_profile_id = preferred_profile_id

    return scene


class TestLimits:
    def test_flow_clips_top_out_at_eight_seconds(self) -> None:
        assert _FLOW.max_single_clip_seconds == 8.0

    def test_muse_clips_are_a_fixed_ten_seconds(self) -> None:
        assert _MUSE.max_single_clip_seconds == MUSE_CLIP_DURATION_SECONDS == 10.0

    @pytest.mark.parametrize("seconds", [8.0, 8.1, 9.0, 10.0])
    def test_split_thresholds_differ_by_provider(self, seconds: float) -> None:
        assert _FLOW.needs_split(seconds) is (seconds > 8.0)
        assert _MUSE.needs_split(seconds) is (seconds > 10.0)


class TestSingleClipLength:
    def test_flow_rounds_up_to_its_verified_grid(self) -> None:
        assert _FLOW.single_clip_seconds(5.0) == 6.0
        assert _FLOW.single_clip_seconds(6.4) == 8.0
        assert _FLOW.single_clip_seconds(8.0) == 8.0

    def test_muse_is_trimmed_to_the_exact_narration_and_capped_at_ten(self) -> None:
        assert _MUSE.single_clip_seconds(6.4) == 6.4
        assert _MUSE.single_clip_seconds(10.0) == 10.0
        assert _MUSE.single_clip_seconds(12.0) == 10.0


class TestPlanClips:
    def test_flow_uses_the_cheapest_covering_combination(self) -> None:
        assert _FLOW.plan_clips(9.0) == [6.0, 4.0]

    def test_muse_splits_only_past_ten_seconds_with_exact_even_shares(self) -> None:
        assert _MUSE.plan_clips(9.0) == [9.0]
        assert _MUSE.plan_clips(13.0) == [6.5, 6.5]


class TestFinalizePrompt:
    _PROMPT = (
        "Action. Shot progression: [0-4s] wide; [4-8s] close. "
        "Composition: tight. Duration: 8 seconds."
    )

    def test_both_providers_correct_the_stated_duration(self) -> None:
        assert "Duration: 6 seconds." in _FLOW.finalize_prompt(self._PROMPT, 6.0)
        assert "Duration: 6 seconds." in _MUSE.finalize_prompt(self._PROMPT, 6.0)

    def test_flow_never_adds_a_trim_instruction(self) -> None:
        assert "trim" not in _FLOW.finalize_prompt(self._PROMPT, 6.0)

    def test_muse_asks_to_trim_a_clip_shorter_than_its_fixed_length(self) -> None:
        text = _MUSE.finalize_prompt(self._PROMPT, 7.0)

        assert text.endswith(
            "Also trim the generated 10 seconds video to only 7 seconds video."
        )

    def test_muse_does_not_trim_within_half_a_second_of_its_fixed_length(self) -> None:
        assert "trim" not in _MUSE.finalize_prompt(self._PROMPT, 9.6)
        assert "trim" not in _MUSE.finalize_prompt(self._PROMPT, 10.0)

    def test_muse_trims_just_outside_the_tolerance(self) -> None:
        assert "trim" in _MUSE.finalize_prompt(self._PROMPT, 9.4)


class TestResolveSceneVideoProvider:
    _NAMES = {"muse.1": "Muse", "flow.1": "Google Flow"}

    def test_the_projects_provider_decides_when_the_scene_has_no_account(self) -> None:
        assert (
            resolve_scene_video_provider(_job(VideoProvider.MUSE), _scene())
            == VideoProvider.MUSE
        )
        assert (
            resolve_scene_video_provider(_job(VideoProvider.GOOGLE_FLOW), _scene())
            == VideoProvider.GOOGLE_FLOW
        )

    def test_a_default_job_is_google_flow(self) -> None:
        assert _job().video_provider == VideoProvider.GOOGLE_FLOW

    def test_an_explicit_scene_account_beats_the_project(self) -> None:
        assert (
            resolve_scene_video_provider(
                _job(VideoProvider.GOOGLE_FLOW), _scene("muse.1"), self._NAMES.get
            )
            == VideoProvider.MUSE
        )
        assert (
            resolve_scene_video_provider(
                _job(VideoProvider.MUSE), _scene("flow.1"), self._NAMES.get
            )
            == VideoProvider.GOOGLE_FLOW
        )

    def test_an_account_that_cannot_be_resolved_falls_back_to_the_project(self) -> None:
        assert (
            resolve_scene_video_provider(
                _job(VideoProvider.MUSE), _scene("gone"), self._NAMES.get
            )
            == VideoProvider.MUSE
        )

    def test_without_a_resolver_the_project_decides(self) -> None:
        assert (
            resolve_scene_video_provider(_job(VideoProvider.MUSE), _scene("flow.1"))
            == VideoProvider.MUSE
        )

    def test_provider_names_are_matched_case_insensitively(self) -> None:
        assert (
            resolve_scene_video_provider(_job(), _scene("m"), {"m": "  MUSE "}.get)
            == VideoProvider.MUSE
        )


def test_an_existing_saved_job_without_the_field_loads_as_google_flow() -> None:
    """Back-compat: jobs saved before video_provider existed keep working."""

    job = _job(VideoProvider.MUSE)
    data = job.model_dump(mode="json")
    del data["video_provider"]

    assert VideoJob.model_validate(data).video_provider == VideoProvider.GOOGLE_FLOW
