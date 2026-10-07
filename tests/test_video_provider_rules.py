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

    def test_muse_is_trimmed_to_the_narration_rounded_up_and_capped_at_ten(
        self,
    ) -> None:
        # Rounded UP to a whole second so the picture is never shorter than the
        # voice (7.38s of narration used to get a 7s clip).
        assert _MUSE.single_clip_seconds(6.4) == 7.0
        assert _MUSE.single_clip_seconds(7.0) == 7.0
        assert _MUSE.single_clip_seconds(7.38) == 8.0
        assert _MUSE.single_clip_seconds(4.32) == 5.0
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

    def test_muse_only_states_the_length_of_a_clip_shorter_than_its_fixed_length(
        self,
    ) -> None:
        """Live, 2026-10-07: asking Muse to trim a 10 s clip cut off what it had
        planned; stating the length alone returned exactly that length."""

        text = _MUSE.finalize_prompt(self._PROMPT, 7.0)

        assert "Duration: 7 seconds." in text
        assert "trim" not in text

    def test_the_trim_instruction_can_be_switched_back_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.services.video_provider_rules.MUSE_SEND_TRIM_INSTRUCTION", True
        )

        assert _MUSE.finalize_prompt(self._PROMPT, 7.0).endswith(
            "Also trim the generated 10 seconds video to only 7 seconds video."
        )

    def test_muse_does_not_trim_within_half_a_second_of_its_fixed_length(self) -> None:
        assert "trim" not in _MUSE.finalize_prompt(self._PROMPT, 9.6)
        assert "trim" not in _MUSE.finalize_prompt(self._PROMPT, 10.0)

    def test_muse_rounds_up_so_9_4_seconds_needs_the_full_ten_and_no_trim(
        self,
    ) -> None:
        assert "trim" not in _MUSE.finalize_prompt(self._PROMPT, 9.4)

    def test_muse_trims_when_the_rounded_target_is_clearly_under_ten(self) -> None:
        text = _MUSE.finalize_prompt(self._PROMPT, 8.4)

        assert "Duration: 9 seconds." in text
        assert "trim" not in text


class TestFlatActionIsTimeBoxed:
    """2026-10-03: a shot plan with no BEATS compiles to a flat
    "Action progression" line - WHAT happens, not WHEN. Muse trims its fixed
    10s video to N seconds, so without a time box the needed content can land
    after second N and be cut."""

    _FLAT = (
        "Identity: none. Environment: kitchen. Lighting: warm. "
        "Action progression: A jar of honey is shown, then a spoon lifts it. "
        "Composition: tight. Lens/camera: 50mm, close up. Duration: 8 seconds."
    )

    def test_muse_time_boxes_the_action_to_the_trimmed_length(self) -> None:
        text = _MUSE.finalize_prompt(self._FLAT, 4.0)

        assert (
            "Shot progression: [0-4s] A jar of honey is shown, then a spoon lifts it."
            in text
        )
        assert "Action progression:" not in text
        assert "Duration: 4 seconds." in text
        assert "trim" not in text

    def test_flow_gets_the_same_time_box_for_its_clip_length(self) -> None:
        text = _FLOW.finalize_prompt(self._FLAT, 6.0)

        assert "Shot progression: [0-6s] A jar of honey" in text
        assert "Action progression:" not in text

    def test_muse_writes_a_whole_second_window(self) -> None:
        assert "[0-4s]" in _MUSE.finalize_prompt(self._FLAT, 3.5)

    def test_a_non_whole_length_is_written_without_trailing_zeros(self) -> None:
        # Flow is not rounded: its own length rules apply upstream.
        assert "[0-3.5s]" in _FLOW.finalize_prompt(self._FLAT, 3.5)

    def test_existing_timed_beats_are_left_alone(self) -> None:
        prompt = (
            "Action. Shot progression: [0-2s] a; [2-4s] b. Composition: x. "
            "Duration: 8 seconds."
        )

        text = _MUSE.finalize_prompt(prompt, 4.0)

        assert "[0-2s] a; [2-4s] b." in text
        assert text.count("Shot progression:") == 1

    def test_an_action_containing_sentences_is_kept_whole(self) -> None:
        prompt = (
            "Action progression: Honey pours. It glows. Then it stops. "
            "Composition: x. Duration: 8 seconds."
        )

        text = _FLOW.finalize_prompt(prompt, 4.0)

        assert "Shot progression: [0-4s] Honey pours. It glows. Then it stops." in text

    def test_a_prompt_with_neither_form_is_unchanged_apart_from_duration(self) -> None:
        prompt = "Just some text. Duration: 8 seconds."

        assert (
            _FLOW.finalize_prompt(prompt, 4.0) == "Just some text. Duration: 4 seconds."
        )


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


class TestMuseMinimumClipLength:
    """2026-10-04: Muse never generates a single clip shorter than 3 seconds."""

    def test_a_one_second_scene_gets_the_floor(self) -> None:
        assert _MUSE.single_clip_seconds(1.0) == 3.0
        assert _MUSE.single_clip_seconds(2.9) == 3.0

    def test_the_floor_itself_and_longer_scenes_are_unchanged(self) -> None:
        assert _MUSE.single_clip_seconds(3.0) == 3.0
        assert _MUSE.single_clip_seconds(6.0) == 6.0
        assert _MUSE.single_clip_seconds(10.0) == 10.0

    def test_the_ten_second_ceiling_still_applies(self) -> None:
        assert _MUSE.single_clip_seconds(12.0) == 10.0

    def test_flow_is_untouched(self) -> None:
        assert _FLOW.single_clip_seconds(1.0) == 4.0
        assert _FLOW.single_clip_seconds(5.0) == 6.0

    def test_split_scenes_are_not_affected(self) -> None:
        assert _MUSE.plan_clips(13.0) == [6.5, 6.5]

    def test_the_prompt_asks_for_the_floor_not_the_narration(self) -> None:
        prompt = (
            "Action progression: A jar of honey. Composition: tight. "
            "Duration: 8 seconds."
        )

        text = _MUSE.finalize_prompt(prompt, _MUSE.single_clip_seconds(1.0))

        assert "Duration: 3 seconds." in text
        assert "[0-3s] A jar of honey." in text
        assert "trim" not in text


class TestSplitScenesDurationLine:
    """Live, 2026-10-06 (scene 30): a split Muse prompt said "Duration: 6 seconds
    (part 1 of 2)." and then asked Muse to trim to "only 7 seconds" - the duration
    line was only rewritten in its "N seconds." form."""

    _PART = (
        "Identity: x. Shot progression: [0-4s] a; [4-7s] b. Composition: tight. "
        "Duration: 6 seconds (part 1 of 2)."
    )

    def test_muse_rewrites_the_split_form_to_the_rounded_up_length(self) -> None:
        text = _MUSE.finalize_prompt(self._PART, 6.48)

        assert "Duration: 7 seconds (part 1 of 2)." in text
        assert "Duration: 6 seconds" not in text
        assert "trim" not in text

    def test_the_part_label_survives(self) -> None:
        text = _MUSE.finalize_prompt(
            self._PART.replace("part 1 of 2", "part 2 of 2"), 6.48
        )

        assert "(part 2 of 2)." in text

    def test_flow_rewrites_the_split_form_too(self) -> None:
        text = _FLOW.finalize_prompt(self._PART, 8.0)

        assert "Duration: 8 seconds (part 1 of 2)." in text

    def test_the_plain_form_is_still_rewritten(self) -> None:
        text = _MUSE.finalize_prompt("Composition: x. Duration: 8 seconds.", 7.0)

        assert "Duration: 7 seconds." in text


class TestMuseStatesItsLengthWhenThePromptHasNone:
    """With the trim instruction gone, the stated "Duration: N seconds." is the only
    way Muse is told the length - so a prompt without one (no compiled prompt, or a
    hand-written one) gets it added."""

    def test_a_missing_duration_line_is_added(self) -> None:
        text = _MUSE.finalize_prompt("A jar of honey on a counter.", 5.0)

        assert text.endswith("Duration: 5 seconds.")
        assert "trim" not in text

    def test_an_existing_duration_line_is_not_repeated(self) -> None:
        text = _MUSE.finalize_prompt("A jar. Duration: 8 seconds.", 5.0)

        assert text.count("Duration:") == 1
        assert "Duration: 5 seconds." in text

    def test_flow_prompts_are_left_alone(self) -> None:
        assert "Duration" not in _FLOW.finalize_prompt("A jar of honey.", 6.0)
