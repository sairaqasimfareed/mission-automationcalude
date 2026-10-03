"""
Render pipeline audit, 2026-10-03: the stored RenderResult.duration_seconds
must be the real encoded file's length, not the timeline's computed end.
Real ffmpeg + ffprobe, no mocked probe - the unit tests in test_render_stage
use a fake one.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.models.render_result import RenderResult, RenderStatus
from src.pipeline.render_stage import RenderPipelineStage

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Real duration test requires ffmpeg and ffprobe.",
)


def test_the_stage_records_the_real_file_length_not_the_stale_computed_one(
    tmp_path: Path,
) -> None:
    from tests.test_render_stage import (  # noqa: PLC0415
        _fake_production_render_service,
        _job_ready_to_render,
        build_context,
    )

    real_file = tmp_path / "final_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=3.4",
            "-pix_fmt",
            "yuv420p",
            str(real_file),
        ],
        check=True,
        capture_output=True,
    )

    fake = _fake_production_render_service()
    # The timeline said 100s; the file on disk is 3.4s.
    fake.render.return_value = RenderResult(
        success=True,
        output_file=real_file.as_posix(),
        render_engine="ffmpeg",
        duration_seconds=100,
        status=RenderStatus.COMPLETED,
    )
    stage = RenderPipelineStage(
        production_render_service=fake,
        voice_blueprints=[MagicMock()],
    )
    job = _job_ready_to_render()

    stage.execute(build_context(job))

    assert job.render_result is not None
    assert job.render_result.duration_seconds == 3
