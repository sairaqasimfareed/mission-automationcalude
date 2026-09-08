"""
Downloads a real, static Windows FFmpeg/FFprobe build and places it
under dist\\MissionAutomation\\tools\\ffmpeg\\, matching where
FFmpegCapabilityService._bundled_tool_path() looks for it.

Run AFTER the PyInstaller build (dist\\MissionAutomation\\ must
already exist) and BEFORE compiling the Inno Setup installer:

    .venv\\Scripts\\python.exe packaging\\fetch_ffmpeg.py

Source: gyan.dev's "essentials" static Windows builds
(https://www.gyan.dev/ffmpeg/builds/) - a well-known, widely-used
static-build provider for Windows FFmpeg, real GPL-licensed FFmpeg
source compiled statically, not a re-implementation. The exact
release used and verified for this project (2026-09-08): FFmpeg
9.0.1. This script always fetches the current "release-essentials"
build, not a version pin - re-run this and rebuild the installer
periodically to stay current, and note the actual version this
prints the next time this project's own docs are updated, matching
the "every machine uses the identical, tested FFmpeg version" goal
this bundling exists for in the first place.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist" / "MissionAutomation"
TARGET_DIR = DIST_DIR / "tools" / "ffmpeg"
DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def main() -> int:
    if not DIST_DIR.is_dir():
        print(
            f"ERROR: {DIST_DIR} does not exist yet - build with PyInstaller first "
            "(see packaging/README.md)."
        )
        return 1

    print(f"Downloading {DOWNLOAD_URL} ...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "ffmpeg-release.zip"

        response = requests.get(DOWNLOAD_URL, timeout=300)
        response.raise_for_status()
        zip_path.write_bytes(response.content)

        print(f"Downloaded {len(response.content) / 1_000_000:.1f} MB, extracting...")

        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp_path)

        # The archive's own top-level folder is versioned (e.g.
        # "ffmpeg-9.0.1-essentials_build") - find bin/ffmpeg.exe
        # rather than hardcoding a version-specific path, since the
        # download URL itself always points at the current release.
        ffmpeg_exe = next(tmp_path.glob("*/bin/ffmpeg.exe"), None)
        ffprobe_exe = next(tmp_path.glob("*/bin/ffprobe.exe"), None)

        if ffmpeg_exe is None or ffprobe_exe is None:
            print("ERROR: ffmpeg.exe/ffprobe.exe not found in the downloaded archive.")
            return 1

        TARGET_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ffmpeg_exe, TARGET_DIR / "ffmpeg.exe")
        shutil.copy2(ffprobe_exe, TARGET_DIR / "ffprobe.exe")

    print(f"Placed ffmpeg.exe and ffprobe.exe under {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
