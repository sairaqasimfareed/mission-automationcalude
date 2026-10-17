"""Put the installer's bundled FFmpeg/FFprobe on PATH for the whole process.

The installed app ships ffmpeg.exe and ffprobe.exe in tools\ffmpeg beside MissionAutomation.exe, but only the
render step looked there. Everything else (checking a downloaded clip with ffprobe, trimming it, pulling a
frame out of it) just runs "ffmpeg"/"ffprobe" from PATH - fine on a developer machine, but on a PC without
FFmpeg installed a freshly downloaded video failed its check and was never attached to its clip.
Prepending the bundled folder once, at start-up, fixes every one of those callers at the same time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bundled_ffmpeg_directory() -> Path | None:
    """tools/ffmpeg next to the frozen executable, when the installer put one there."""

    if not getattr(sys, "frozen", False):
        return None

    candidate = Path(sys.executable).resolve().parent / "tools" / "ffmpeg"

    return candidate if (candidate / "ffprobe.exe").is_file() else None


def add_bundled_tools_to_path() -> str | None:
    """Prepend the bundled FFmpeg folder to PATH. Returns the folder added, or None."""

    directory = bundled_ffmpeg_directory()

    if directory is None:
        return None

    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []

    if str(directory) not in entries:
        os.environ["PATH"] = os.pathsep.join([str(directory), *entries])

    return str(directory)


def use_install_folder_as_working_directory() -> str | None:
    """Make the folder holding MissionAutomation.exe the working directory (installed app only).

    The app keeps its projects, settings and logs in folders RELATIVE to the working directory (data, logs).
    Started from the Start Menu shortcut that is the install folder, but started any other way (a pinned
    taskbar icon, "Open with", a command prompt elsewhere) it would silently use an empty data folder
    somewhere else and look as if every project and provider had vanished."""

    if not getattr(sys, "frozen", False):
        return None

    folder = Path(sys.executable).resolve().parent

    try:
        os.chdir(folder)
    except OSError:
        return None

    return str(folder)
