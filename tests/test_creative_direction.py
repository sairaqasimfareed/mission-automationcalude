from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.creative_direction import CreativeDirection
from src.models.story_angle import StoryAngle, StoryAngleStyle


def _angle(**overrides: object) -> StoryAngle:
    base: dict[str, object] = dict(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the ship's missing final log entry.",
    )
    base.update(overrides)
    return StoryAngle(**base)


def test_valid_creative_direction_constructs() -> None:
    direction = CreativeDirection(
        selected_angle=_angle(),
        narrative_thesis="The crew's disappearance was foreshadowed by the logbook.",
        constraints=["No supernatural framing", "Keep under 8 minutes"],
    )

    assert direction.selected_angle.title == "The Missing Logbook"
    assert direction.combined_angle_note is None
    assert direction.constraints == ["No supernatural framing", "Keep under 8 minutes"]


def test_blank_narrative_thesis_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        CreativeDirection(selected_angle=_angle(), narrative_thesis="   ")


def test_blank_combined_angle_note_normalizes_to_none() -> None:
    direction = CreativeDirection(
        selected_angle=_angle(),
        narrative_thesis="A thesis.",
        combined_angle_note="   ",
    )

    assert direction.combined_angle_note is None


def test_combined_angle_note_can_be_set() -> None:
    direction = CreativeDirection(
        selected_angle=_angle(),
        narrative_thesis="A thesis.",
        combined_angle_note="Merges the mystery framing with the investigation angle.",
    )

    assert direction.combined_angle_note == (
        "Merges the mystery framing with the investigation angle."
    )


def test_constraints_default_to_empty_list() -> None:
    direction = CreativeDirection(selected_angle=_angle(), narrative_thesis="A thesis.")

    assert direction.constraints == []


def test_constraints_strip_whitespace_and_drop_blank_entries() -> None:
    direction = CreativeDirection(
        selected_angle=_angle(),
        narrative_thesis="A thesis.",
        constraints=["  No jump scares  ", "", "   "],
    )

    assert direction.constraints == ["No jump scares"]


def test_backward_compatible_round_trip_from_video_job_without_creative_direction() -> (
    None
):
    from src.models.video_job import VideoJob

    job = VideoJob(project_name="p", channel_name="c", niche="n", topic="t")
    raw = job.model_dump_json()

    reloaded = VideoJob.model_validate_json(raw)

    assert reloaded.creative_direction is None


def test_creative_direction_round_trips_on_a_video_job() -> None:
    from src.models.video_job import VideoJob

    job = VideoJob(project_name="p", channel_name="c", niche="n", topic="t")
    job.creative_direction = CreativeDirection(
        selected_angle=_angle(),
        narrative_thesis="A thesis.",
        constraints=["Keep it grounded"],
    )

    raw = job.model_dump_json()
    reloaded = VideoJob.model_validate_json(raw)

    assert reloaded.creative_direction is not None
    assert reloaded.creative_direction.narrative_thesis == "A thesis."
    assert reloaded.creative_direction.constraints == ["Keep it grounded"]
