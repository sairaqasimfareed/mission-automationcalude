"""A clip stored longer than its file (Salem scene 1 part 1: 6 s file stored as 8 s) made the
timeline's picture join end early - 11 s of video under 104 s of audio. The stored length is
corrected to the real one; a longer file is left alone."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.asset_state import AssetCandidate, SceneAssetState
from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip, VideoClipStatus
from src.services.clip_real_length import correct_short_clip_lengths, real_clip_seconds
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="needs a real ffmpeg"
)


def _video(tmp_path: Path, seconds: int, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=160x90:d={seconds}:r=24",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _clip(path: str | None, stored: int) -> VideoClip:
    return VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=stored,
        local_file=path,
        status=VideoClipStatus.READY,
    )


def test_a_file_shorter_than_its_stored_length_is_corrected(tmp_path: Path) -> None:
    clip = _clip(str(_video(tmp_path, 2)), stored=5)

    changed = correct_short_clip_lengths([clip])

    assert changed == [clip]
    assert clip.duration_seconds == 2


def test_a_longer_or_matching_or_unreadable_file_keeps_its_stored_length(
    tmp_path: Path,
) -> None:
    longer = _clip(str(_video(tmp_path, 4, "long.mp4")), stored=2)
    same = _clip(str(_video(tmp_path, 3, "same.mp4")), stored=3)
    missing = _clip(str(tmp_path / "nope.mp4"), stored=6)

    assert correct_short_clip_lengths([longer, same, missing]) == []
    assert [c.duration_seconds for c in (longer, same, missing)] == [
        2,
        3,
        6,
    ]
    assert real_clip_seconds(str(tmp_path / "nope.mp4")) is None


def test_a_manual_upload_without_a_length_is_built_with_the_files_own(
    tmp_path: Path,
) -> None:
    path = _video(tmp_path, 3)
    state = SceneAssetState(scene_id="s1", scene_number=1)
    candidate = AssetCandidate(
        title="x",
        source_type=SceneSourceType.MANUAL_UPLOAD,
        file_path=str(path),
        provider="Manual Upload",
        duration_seconds=0.0,
    )
    state.selected_candidate = candidate
    state.selected_source = SceneSourceType.MANUAL_UPLOAD
    state.status = state.status.__class__.READY

    from src.models.scene import Scene

    scene = Scene(
        scene_number=1,
        title="Scene 1",
        narration="Narration.",
        visual_prompt="A visual.",
        estimated_duration_seconds=8,
    )

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=[scene], states=[state]
    )

    assert [clip.duration_seconds for clip in clips] == [3]
