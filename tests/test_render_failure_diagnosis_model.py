from __future__ import annotations

from src.models.render_failure_diagnosis import (
    RenderFailureCategory,
    classify_render_failure,
)


def test_classify_render_failure_maps_environment_stages() -> None:
    for stage in (
        "process_start",
        "stream_setup",
        "timeout",
        "output_presence",
        "output_type",
        "output_size",
    ):
        assert (
            classify_render_failure(stage) == RenderFailureCategory.ENVIRONMENT
        ), stage


def test_classify_render_failure_maps_ffmpeg_exit_to_command_or_media() -> None:
    assert (
        classify_render_failure("ffmpeg_exit") == RenderFailureCategory.COMMAND_OR_MEDIA
    )


def test_classify_render_failure_maps_cancelled() -> None:
    assert classify_render_failure("cancelled") == RenderFailureCategory.CANCELLED


def test_classify_render_failure_returns_none_for_unknown_stage() -> None:
    assert classify_render_failure("some_future_stage_this_map_predates") is None


def test_classify_render_failure_returns_none_for_missing_stage() -> None:
    assert classify_render_failure(None) is None
    assert classify_render_failure("") is None
