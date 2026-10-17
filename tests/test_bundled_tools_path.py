"""An installed app on a PC without FFmpeg must still find ffmpeg/ffprobe for every step, not only the render
(found 2026-10-16: a downloaded clip failed its ffprobe check and was never attached).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src.shared.bundled_tools import (
    add_bundled_tools_to_path,
    bundled_ffmpeg_directory,
    use_install_folder_as_working_directory,
)


def _install(tmp_path: Path) -> Path:
    tools = tmp_path / "tools" / "ffmpeg"
    tools.mkdir(parents=True)
    (tools / "ffprobe.exe").write_bytes(b"x")
    (tools / "ffmpeg.exe").write_bytes(b"x")

    return tools


def test_the_bundled_folder_is_put_first_on_path(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    tools = _install(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MissionAutomation.exe"))
    monkeypatch.setenv("PATH", "C:\other")

    assert add_bundled_tools_to_path() == str(tools)
    assert os.environ["PATH"].split(os.pathsep)[0] == str(tools)
    assert "C:\other" in os.environ["PATH"]


def test_adding_it_twice_does_not_repeat_it(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    tools = _install(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MissionAutomation.exe"))
    monkeypatch.setenv("PATH", "C:\other")

    add_bundled_tools_to_path()
    add_bundled_tools_to_path()

    assert os.environ["PATH"].split(os.pathsep).count(str(tools)) == 1


def test_a_development_run_leaves_path_alone(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("PATH", "C:\other")

    assert bundled_ffmpeg_directory() is None
    assert add_bundled_tools_to_path() is None
    assert os.environ["PATH"] == "C:\other"


def test_an_install_without_the_tools_folder_changes_nothing(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MissionAutomation.exe"))
    monkeypatch.setenv("PATH", "C:\other")

    assert add_bundled_tools_to_path() is None
    assert os.environ["PATH"] == "C:\other"


def test_the_installed_app_works_from_its_own_folder(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MissionAutomation.exe"))

    assert use_install_folder_as_working_directory() == str(tmp_path.resolve())
    assert Path.cwd() == tmp_path.resolve()


def test_a_development_run_keeps_its_working_directory(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert use_install_folder_as_working_directory() is None
    assert Path.cwd() == tmp_path.resolve()
