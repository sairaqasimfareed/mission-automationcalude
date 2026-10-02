from __future__ import annotations

from src.shared.dry_run_placeholder import is_dry_run_placeholder


def test_recognizes_every_real_dry_run_provider_placeholder_shape() -> None:
    assert is_dry_run_placeholder("dry-run://voice/neutral_narrator.mp3")
    assert is_dry_run_placeholder("dry-run://music/a_sting.mp3")
    assert is_dry_run_placeholder("dry-run://sfx/whoosh.mp3")
    assert is_dry_run_placeholder("dry-run://thumbnail/1920x1080.png")


def test_a_real_local_file_path_is_not_a_placeholder() -> None:
    assert not is_dry_run_placeholder("C:/Users/Test/background.jpg")
    assert not is_dry_run_placeholder("/tmp/real_file.mp3")
    assert not is_dry_run_placeholder("outputs/final_video.mp4")


def test_none_is_not_a_placeholder() -> None:
    assert not is_dry_run_placeholder(None)
