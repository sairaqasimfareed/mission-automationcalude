from __future__ import annotations

import pytest

from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.retention_audit_service import RetentionAuditService

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _mystery_profile() -> object:
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.mystery")
    )


def _clean_blueprint() -> StoryBlueprint:
    # genre.mystery: reveal_density_per_minute=3.0 -> expects 6 reveals in
    # 120s, spaced no more than 40s apart. Six reveal beats every 20s
    # satisfies both, and tension varies well beyond the 20-point floor.
    tensions = [30, 50, 70, 90, 60, 40]

    return StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=120,
        prompt_version="story_blueprint_prompt_v1.0.0",
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.REVEAL,
                start_seconds=index * 20,
                end_seconds=(index + 1) * 20,
                purpose=f"Reveal {index + 1}.",
                tension_level=tensions[index],
            )
            for index in range(6)
        ],
    )


def test_audit_of_clean_blueprint_has_no_findings() -> None:
    service = RetentionAuditService()

    report = service.audit(
        topic="The Mary Celeste",
        blueprint=_clean_blueprint(),
        editorial_profile=_mystery_profile(),
    )

    assert report.passed is True
    assert report.reveal_count == 6
    assert report.expected_minimum_reveal_count == 6


def test_audit_flags_insufficient_reveal_density() -> None:
    blueprint = StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=60,
        prompt_version="story_blueprint_prompt_v1.0.0",
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=15,
                purpose="Open with the mystery.",
                tension_level=40,
            ),
            StoryBeat(
                beat_type=StoryBeatType.SETUP,
                start_seconds=15,
                end_seconds=45,
                purpose="Lay out known facts.",
                tension_level=45,
            ),
            StoryBeat(
                beat_type=StoryBeatType.REVEAL,
                start_seconds=45,
                end_seconds=60,
                purpose="Reveal the theory.",
                tension_level=80,
            ),
        ],
    )

    service = RetentionAuditService()

    report = service.audit(
        topic="The Mary Celeste",
        blueprint=blueprint,
        editorial_profile=_mystery_profile(),
    )

    issue_types = {finding.issue_type.value for finding in report.findings}

    assert "insufficient_reveal_density" in issue_types
    assert report.reveal_count == 1
    assert report.expected_minimum_reveal_count == 3


def test_audit_flags_a_long_gap_without_a_reveal() -> None:
    blueprint = StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=120,
        prompt_version="story_blueprint_prompt_v1.0.0",
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.REVEAL,
                start_seconds=index * 10,
                end_seconds=(index + 1) * 10,
                purpose=f"Reveal {index + 1}.",
                tension_level=[30, 50, 70, 90, 60, 40][index],
            )
            for index in range(6)
        ]
        + [
            StoryBeat(
                beat_type=StoryBeatType.ESCALATION,
                start_seconds=60,
                end_seconds=120,
                purpose="Let tension build toward the finale.",
                tension_level=80,
            )
        ],
    )

    service = RetentionAuditService()

    report = service.audit(
        topic="The Mary Celeste",
        blueprint=blueprint,
        editorial_profile=_mystery_profile(),
    )

    issue_types = {finding.issue_type.value for finding in report.findings}

    assert "reveal_gap_too_long" in issue_types
    assert "insufficient_reveal_density" not in issue_types


def test_audit_flags_low_tension_variation() -> None:
    blueprint = StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=120,
        prompt_version="story_blueprint_prompt_v1.0.0",
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.REVEAL,
                start_seconds=index * 20,
                end_seconds=(index + 1) * 20,
                purpose=f"Reveal {index + 1}.",
                tension_level=50,
            )
            for index in range(6)
        ],
    )

    service = RetentionAuditService()

    report = service.audit(
        topic="The Mary Celeste",
        blueprint=blueprint,
        editorial_profile=_mystery_profile(),
    )

    issue_types = {finding.issue_type.value for finding in report.findings}

    assert issue_types == {"low_tension_variation"}


def test_audit_rejects_empty_topic() -> None:
    service = RetentionAuditService()

    with pytest.raises(ValueError, match="cannot be empty"):
        service.audit(
            topic="   ",
            blueprint=_clean_blueprint(),
            editorial_profile=_mystery_profile(),
        )
