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
    override_reason: str | None = None,
) -> ScriptLock:
    return ScriptLock(
        script_version_number=script_version_number,
        script_content_hash=script_content_hash,
        provenance=provenance,
        quality_status=quality_status,
        override_reason=override_reason,
    )


def test_constructs_with_required_fields() -> None:
    lock = _lock()

    assert lock.script_version_number == 1
    assert lock.provenance == ScriptProvenance.INTERNAL
    assert lock.override_reason is None


def test_rejects_a_blank_content_hash() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _lock(script_content_hash="   ")


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
