from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.script_lock import ScriptLock, ScriptProvenance
from src.models.script_quality_report import ScriptQualityStatus


def _lock(
    *,
    script_version_number: int = 1,
    script_content_hash: str = "a" * 64,
    provenance: ScriptProvenance = ScriptProvenance.INTERNAL,
    quality_status: (
        ScriptQualityStatus | None
    ) = ScriptQualityStatus.APPROVED_FOR_PRODUCTION,
    topic: str | None = "The Mary Celeste",
    angle: str | None = None,
    target_duration_seconds: int | None = 180,
    genre_id: str | None = "genre.mystery",
    override_reason: str | None = None,
) -> ScriptLock:
    return ScriptLock(
        script_version_number=script_version_number,
        script_content_hash=script_content_hash,
        provenance=provenance,
        quality_status=quality_status,
        topic=topic,
        angle=angle,
        target_duration_seconds=target_duration_seconds,
        genre_id=genre_id,
        override_reason=override_reason,
    )


def test_constructs_with_required_fields() -> None:
    lock = _lock()

    assert lock.script_version_number == 1
    assert lock.provenance == ScriptProvenance.INTERNAL
    assert lock.override_reason is None
    assert lock.topic == "The Mary Celeste"
    assert lock.angle is None
    assert lock.target_duration_seconds == 180
    assert lock.genre_id == "genre.mystery"


def test_rejects_a_blank_content_hash() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _lock(script_content_hash="   ")


def test_topic_angle_duration_and_genre_default_to_none() -> None:
    """
    Backward compatibility: a ScriptLock JSON blob persisted before
    this fix has no topic/angle/target_duration_seconds/genre_id keys
    at all - JsonJobStore's raw model_validate_json() must still load
    it cleanly, with these fields honestly unset rather than a
    migration guessing a value.
    """

    lock = ScriptLock(
        script_version_number=1,
        script_content_hash="a" * 64,
        provenance=ScriptProvenance.INTERNAL,
    )

    assert lock.topic is None
    assert lock.angle is None
    assert lock.target_duration_seconds is None
    assert lock.genre_id is None


def test_blank_topic_becomes_none() -> None:
    lock = _lock(topic="   ")

    assert lock.topic is None


def test_blank_genre_id_becomes_none() -> None:
    lock = _lock(genre_id="   ")

    assert lock.genre_id is None


def test_topic_and_genre_id_are_stripped_when_present() -> None:
    lock = _lock(topic="  The Mary Celeste  ", genre_id="  genre.mystery  ")

    assert lock.topic == "The Mary Celeste"
    assert lock.genre_id == "genre.mystery"


def test_rejects_a_non_positive_target_duration() -> None:
    with pytest.raises(ValidationError):
        _lock(target_duration_seconds=0)


def test_angle_blank_becomes_none() -> None:
    lock = _lock(angle="   ")

    assert lock.angle is None


def test_angle_is_stripped_when_present() -> None:
    lock = _lock(angle="  A ghost ship investigation.  ")

    assert lock.angle == "A ghost ship investigation."


def test_override_reason_blank_becomes_none() -> None:
    lock = _lock(override_reason="   ")

    assert lock.override_reason is None


def test_override_reason_is_stripped() -> None:
    lock = _lock(override_reason="  Approved by lead editor.  ")

    assert lock.override_reason == "Approved by lead editor."


def test_quality_status_may_be_none() -> None:
    lock = _lock(quality_status=None)

    assert lock.quality_status is None


def test_external_provenance() -> None:
    lock = _lock(provenance=ScriptProvenance.EXTERNAL)

    assert lock.provenance == ScriptProvenance.EXTERNAL
