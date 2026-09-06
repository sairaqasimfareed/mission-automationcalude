from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.production_provenance import ProductionProvenance


def test_defaults_are_all_unset_or_zero() -> None:
    provenance = ProductionProvenance()

    assert provenance.script_lock_hash is None
    assert provenance.script_version_number is None
    assert provenance.video_item_count == 0
    assert provenance.audio_track_count == 0
    assert provenance.voice_track_count == 0
    assert provenance.render_engine is None
    assert provenance.render_exit_code is None
    assert provenance.render_ffmpeg_command == []


def test_stores_every_explicit_field() -> None:
    provenance = ProductionProvenance(
        script_lock_hash="deadbeef" * 4,
        script_version_number=3,
        video_item_count=5,
        audio_track_count=2,
        voice_track_count=1,
        render_engine="ffmpeg",
        render_exit_code=1,
        render_ffmpeg_command=["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"],
    )

    assert provenance.script_lock_hash == "deadbeef" * 4
    assert provenance.script_version_number == 3
    assert provenance.video_item_count == 5
    assert provenance.audio_track_count == 2
    assert provenance.voice_track_count == 1
    assert provenance.render_engine == "ffmpeg"
    assert provenance.render_exit_code == 1
    assert provenance.render_ffmpeg_command == [
        "ffmpeg",
        "-y",
        "-i",
        "in.mp4",
        "out.mp4",
    ]


def test_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        ProductionProvenance(video_item_count=-1)

    with pytest.raises(ValidationError):
        ProductionProvenance(audio_track_count=-1)

    with pytest.raises(ValidationError):
        ProductionProvenance(voice_track_count=-1)


def test_round_trips_through_serialization() -> None:
    provenance = ProductionProvenance(
        script_lock_hash="abc123",
        script_version_number=2,
        video_item_count=3,
        audio_track_count=4,
        voice_track_count=1,
        render_engine="ffmpeg",
        render_exit_code=0,
        render_ffmpeg_command=["ffmpeg", "-i", "in.mp4", "out.mp4"],
    )

    restored = ProductionProvenance.model_validate_json(provenance.model_dump_json())

    assert restored == provenance
