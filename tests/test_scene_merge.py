"""
Merging short scenes into fewer, longer clips (2026-10-15): a project switch read at scene planning.
Off (no MergeSettings) the planner behaves exactly as before; on, neighbouring short scenes are folded
together while they still fit one clip. A spoken exchange and a one-line beat are never folded in, the
top10 countdown is left alone, and nothing is lost: every word of narration survives in order.
"""

from __future__ import annotations

from src.agents.scene_planner.agent import MergeSettings, ScenePlannerAgent
from src.models.dialogue import DialogueLine
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType
from src.models.video_provider import VideoProvider
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.narration_timing_service import NarrationTimingService
from src.services.video_provider_rules import merge_target_seconds
from tests.test_scene_planner_generated_script import _editorial_profile
from tests.test_suggestions import qapp as qapp  # noqa: PLC0414 - fixture

_SHORT_LINES = (
    "The door was open. It had been locked. Nobody had a key. The room was cold. "
    "A lamp still burned. The bed was made."
)


def _segment(
    number: int,
    start: float,
    end: float,
    narration: str,
    *,
    beat: StoryBeatType = StoryBeatType.SETUP,
    tension: int = 50,
    dialogue: list[DialogueLine] | None = None,
) -> ScriptSegment:
    return ScriptSegment(
        segment_number=number,
        start_seconds=start,
        end_seconds=end,
        narrative_function=beat,
        narration=narration,
        tension_level=tension,
        dialogue=dialogue or [],
    )


def _script(
    *segments: ScriptSegment, genre_id: str = "genre.mystery"
) -> GeneratedScript:
    return GeneratedScript(
        topic="The Locked Room",
        genre_id=genre_id,
        target_duration_seconds=int(max(segment.end_seconds for segment in segments)),
        segments=list(segments),
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _words(scenes) -> list[str]:  # type: ignore[no-untyped-def]
    return " ".join(scene.narration for scene in scenes).split()


def test_without_settings_the_plan_is_exactly_the_normal_one() -> None:
    script = _script(_segment(1, 0, 60, _SHORT_LINES))
    agent = ScenePlannerAgent()
    profile = _editorial_profile()

    default = agent.plan_from_generated_script(script, profile)
    explicit_none = agent.plan_from_generated_script(script, profile, merge=None)

    assert [
        s.model_dump(exclude={"id", "created_at", "updated_at"}) for s in default
    ] == [
        s.model_dump(exclude={"id", "created_at", "updated_at"}) for s in explicit_none
    ]
    assert all("merged_segment_numbers" not in s.metadata for s in default)


def test_merging_gives_fewer_scenes_that_still_hold_every_word_in_order() -> None:
    script = _script(_segment(1, 0, 60, _SHORT_LINES))
    agent = ScenePlannerAgent()
    profile = _editorial_profile()

    normal = agent.plan_from_generated_script(script, profile)
    merged = agent.plan_from_generated_script(
        script, profile, merge=MergeSettings(target_seconds=7.0)
    )

    assert len(normal) > 1
    assert len(merged) < len(normal)
    assert _words(merged) == _words(normal)
    assert [s.scene_number for s in merged] == list(range(1, len(merged) + 1))


def test_a_merged_scene_never_outgrows_the_target() -> None:
    script = _script(_segment(1, 0, 60, _SHORT_LINES * 3))
    timing = NarrationTimingService()
    merged = ScenePlannerAgent().plan_from_generated_script(
        script, _editorial_profile(), merge=MergeSettings(target_seconds=7.0)
    )

    for scene in merged:
        sentences = scene.narration.count(".")
        if (
            sentences > 1
        ):  # a single over-long sentence may stand alone, as it always could
            assert timing.estimate_seconds(len(scene.narration.split())) <= 7


def test_a_lower_target_merges_less() -> None:
    script = _script(_segment(1, 0, 60, _SHORT_LINES))
    agent = ScenePlannerAgent()
    profile = _editorial_profile()

    tight = agent.plan_from_generated_script(
        script, profile, merge=MergeSettings(target_seconds=5.0)
    )
    roomy = agent.plan_from_generated_script(
        script, profile, merge=MergeSettings(target_seconds=9.0)
    )

    assert len(roomy) <= len(tight)


def test_a_spoken_exchange_is_never_merged() -> None:
    lines = [
        DialogueLine(speaker="Walter", text="Who is there?"),
        DialogueLine(speaker="Frank", text="Open the door."),
    ]
    script = _script(
        _segment(1, 0, 10, "The door was open. It was cold."),
        _segment(2, 10, 20, "Who is there? Open the door.", dialogue=lines),
        _segment(3, 20, 30, "Nobody moved. The lamp burned."),
    )

    merged = ScenePlannerAgent().plan_from_generated_script(
        script, _editorial_profile(), merge=MergeSettings(target_seconds=9.0)
    )

    spoken = [s for s in merged if s.dialogue]
    assert len(spoken) == 1
    assert spoken[0].narration == "Who is there? Open the door."
    assert len(spoken[0].dialogue) == 2


def test_a_one_line_beat_stays_alone_unless_told_otherwise() -> None:
    script = _script(
        _segment(1, 0, 10, "The door was open. It had been locked."),
        _segment(2, 10, 14, "Nobody answered.", beat=StoryBeatType.CLIMAX, tension=90),
        _segment(3, 14, 24, "The lamp still burned. The bed was made."),
    )
    agent = ScenePlannerAgent()
    profile = _editorial_profile()

    kept = agent.plan_from_generated_script(
        script, profile, merge=MergeSettings(target_seconds=9.0, keep_beats=True)
    )
    folded = agent.plan_from_generated_script(
        script, profile, merge=MergeSettings(target_seconds=9.0, keep_beats=False)
    )

    assert "Nobody answered." in [s.narration for s in kept]
    assert "Nobody answered." not in [s.narration for s in folded]
    assert len(folded) < len(kept)


def test_the_most_tense_piece_sets_the_merged_scenes_beat() -> None:
    script = _script(
        _segment(1, 0, 8, "The door was open. It was cold.", tension=20),
        _segment(
            2,
            8,
            16,
            "Something moved inside. A hand reached out.",
            beat=StoryBeatType.CLIMAX,
            tension=95,
        ),
    )

    merged = ScenePlannerAgent().plan_from_generated_script(
        script, _editorial_profile(), merge=MergeSettings(target_seconds=9.0)
    )

    assert len(merged) == 1
    assert merged[0].tension_level == 95
    assert merged[0].narrative_function == StoryBeatType.CLIMAX.value
    assert merged[0].metadata["merged_segment_numbers"] == [1, 2]


def test_the_countdown_genre_is_left_alone() -> None:
    script = _script(_segment(1, 0, 60, _SHORT_LINES), genre_id="genre.top10")
    agent = ScenePlannerAgent()
    profile = _editorial_profile("genre.top10")

    normal = agent.plan_from_generated_script(script, profile)
    merged = agent.plan_from_generated_script(
        script, profile, merge=MergeSettings(target_seconds=9.0)
    )

    assert [s.narration for s in merged] == [s.narration for s in normal]


# ---------------------------------------------------------------- pipeline and screen


def test_the_target_depends_on_the_video_provider() -> None:
    assert merge_target_seconds(VideoProvider.MUSE) == 9.0
    assert merge_target_seconds(VideoProvider.GOOGLE_FLOW) == 7.0


def test_the_pipeline_only_merges_when_the_project_asks() -> None:
    from tests.test_scene_detail import _job

    job = _job()
    assert ContentIntelligencePipeline.scene_merge_settings(job) is None

    job.merge_short_scenes = True
    job.keep_beat_lines = False
    job.video_provider = VideoProvider.MUSE
    settings = ContentIntelligencePipeline.scene_merge_settings(job)

    assert settings == MergeSettings(target_seconds=9.0, keep_beats=False)


def test_a_new_project_defaults_to_the_normal_plan() -> None:
    from tests.test_scene_detail import _job

    job = _job()

    assert job.merge_short_scenes is False
    assert job.keep_beat_lines is True


def test_the_planning_panel_shows_the_switch_before_anything_is_planned(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(_job_without_scenes())
    holder = QWidget()
    layout = QVBoxLayout(holder)

    can_run = view._render_scene_planning_panel(layout, job)  # noqa: SLF001
    boxes = holder.findChildren(QCheckBox)
    texts = _texts(holder)

    assert can_run in (True, False)
    assert [b.text() for b in boxes] == [
        "Merge short scenes into fewer, longer clips",
        "Keep one-line beats as their own scene",
    ]
    assert boxes[0].isChecked() is False
    assert boxes[1].isEnabled() is False
    assert not any(t.startswith("Preview:") for t in texts)


def test_switching_it_on_is_saved_on_the_job_and_previewed(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

    from tests.test_suggestions import _studio

    view, job, _errors = _studio(_job_without_scenes())

    view._handle_scene_merge_changed(True, False)  # noqa: SLF001
    saved = view._current_job()  # noqa: SLF001

    assert saved is not None
    assert saved.merge_short_scenes is True
    assert saved.keep_beat_lines is False

    holder = QWidget()
    layout = QVBoxLayout(holder)
    view._render_scene_planning_panel(layout, saved)  # noqa: SLF001
    boxes = holder.findChildren(QCheckBox)

    assert boxes[0].isChecked() is True
    assert boxes[1].isChecked() is False
    assert boxes[1].isEnabled() is True


def test_a_replan_warning_shows_only_when_scenes_already_exist(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    fresh, fresh_job, _ = _studio(_job_without_scenes())
    planned, planned_job, _ = _studio(_job_with_scenes())

    fresh_holder = QWidget()
    planned_holder = QWidget()
    fresh._render_scene_planning_panel(
        QVBoxLayout(fresh_holder), fresh_job
    )  # noqa: SLF001
    planned._render_scene_planning_panel(
        QVBoxLayout(planned_holder), planned_job
    )  # noqa: SLF001

    assert not any("replaces them" in t for t in _texts(fresh_holder))
    assert any("replaces them" in t for t in _texts(planned_holder))


def _job_with_scenes():  # type: ignore[no-untyped-def]
    from tests.test_scene_detail import _job

    return _job(3)


def _job_without_scenes():  # type: ignore[no-untyped-def]
    from tests.test_scene_detail import _job

    job = _job(3)
    job.scenes = []

    return job
