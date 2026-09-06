from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.writing_directives import (
    DirectiveSource,
    WritingDirective,
    WritingDirectiveSet,
)


def test_valid_directive_constructs() -> None:
    directive = WritingDirective(
        text="Never state a claim the research does not support.",
        source=DirectiveSource.SYSTEM,
        overridable=False,
    )

    assert directive.source == DirectiveSource.SYSTEM
    assert directive.overridable is False


def test_directive_rejects_blank_text() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        WritingDirective(text="   ", source=DirectiveSource.USER, overridable=True)


def _set(
    *,
    directives: list[WritingDirective] | None = None,
    prompt_version: str = "writing_directives_prompt_v1.0.0",
) -> WritingDirectiveSet:
    return WritingDirectiveSet(
        directives=(
            directives
            if directives is not None
            else [
                WritingDirective(
                    text="Never state a claim the research does not support.",
                    source=DirectiveSource.SYSTEM,
                    overridable=False,
                ),
                WritingDirective(
                    text="Write in an authoritative tone.",
                    source=DirectiveSource.GENRE,
                    overridable=True,
                ),
            ]
        ),
        prompt_version=prompt_version,
    )


def test_valid_set_constructs() -> None:
    directive_set = _set()

    assert len(directive_set.directives) == 2


def test_set_requires_at_least_one_directive() -> None:
    with pytest.raises(ValidationError):
        WritingDirectiveSet(directives=[], prompt_version="v1")


def test_system_directives_property_filters_by_source() -> None:
    directive_set = _set()

    system_directives = directive_set.system_directives

    assert len(system_directives) == 1
    assert system_directives[0].source == DirectiveSource.SYSTEM
    assert all(d.overridable is False for d in system_directives)


def test_system_directives_property_is_empty_when_none_present() -> None:
    directive_set = WritingDirectiveSet(
        directives=[
            WritingDirective(
                text="Write in an authoritative tone.",
                source=DirectiveSource.GENRE,
                overridable=True,
            ),
        ],
        prompt_version="v1",
    )

    assert directive_set.system_directives == []


def test_backward_compatible_round_trip_from_video_job_without_directives() -> None:
    from src.models.video_job import VideoJob

    job = VideoJob(project_name="p", channel_name="c", niche="n", topic="t")
    raw = job.model_dump_json()

    reloaded = VideoJob.model_validate_json(raw)

    assert reloaded.writing_directives is None
    assert reloaded.project_writing_rules == []
    assert reloaded.user_writing_directives == []
