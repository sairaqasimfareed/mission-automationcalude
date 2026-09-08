"""
PyInstaller spec for Mission Automation's Windows desktop build.

Build from the repo root (paths below are relative to this file's own
directory, resolved via SPECPATH, so the build works regardless of the
caller's current working directory):

    .venv\\Scripts\\pyinstaller.exe packaging\\mission_automation.spec --noconfirm

Produces a one-dir build at dist\\MissionAutomation\\ - deliberately
one-dir, not one-file: the installer-packaging plan (see
PROJECT_PROGRESS.md's matching entries) bundles FFmpeg/FFprobe at a
fixed, predictable location next to the real executable
(tools\\ffmpeg\\ffmpeg.exe - see FFmpegCapabilityService._bundled_tool_path()),
which a one-file build's own temp-extraction-per-run layout cannot
offer.

Real external SDKs this app imports (google-genai, anthropic, openai,
playwright) and PySide6 itself all ship their own PyInstaller hooks
via pyinstaller-hooks-contrib (already a pyinstaller dependency) -
collect_all() is used below only for the ones empirically found to
need it (see this file's own build-verification notes once a real
build has been run and checked), not applied speculatively to every
dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all

REPO_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - PyInstaller injects SPECPATH

sys.path.insert(0, str(REPO_ROOT))

APP_NAME = "MissionAutomation"

# google-genai, anthropic, and openai all dynamically resolve parts of
# their own package data/submodules in ways PyInstaller's static
# import analysis alone does not reliably catch (each ships real
# PyInstaller hooks precisely because of this) - collect_all() pulls
# in each one's binaries/datas/hiddenimports together rather than
# guessing at a partial hiddenimports list by hand.
datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []

for package in ("google.genai", "anthropic", "openai", "playwright"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

# Build-verification finding: collect_all("google.genai") pulls in
# that package's own internal pytest test suite
# (google.genai.tests.*, hundreds of hiddenimports and their .py data
# files) - real dead weight this app never imports or runs, found by
# inspecting a real build's own verbose output. Dropped after
# collection rather than excluded from collect_all() itself, since
# collect_all() has no built-in submodule filter.
hiddenimports = [
    name for name in hiddenimports if not name.startswith("google.genai.tests")
]
datas = [entry for entry in datas if "genai/tests" not in entry[0].replace("\\", "/")]
excludes = ["google.genai.tests"]

analysis = Analysis(
    [str(REPO_ROOT / "src" / "desktop" / "app.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Rendered from the exact same SVG src/desktop/icons.py's own
    # app_icon() renders for the in-app window/taskbar icon (see
    # packaging/README.md and the generation script referenced there)
    # - the packaged .exe's icon matches the running app's own icon.
    icon=str(REPO_ROOT / "packaging" / "assets" / "mission_automation.ico"),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
