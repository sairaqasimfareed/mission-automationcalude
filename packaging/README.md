# Mission Automation - Windows installer packaging

This directory holds the build tooling for producing
`MissionAutomationSetup.exe` - see `PROJECT_PROGRESS.md`'s dated
entries for the full history and decisions behind this setup.

## Build the app (PyInstaller)

```
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\pyinstaller.exe packaging\mission_automation.spec --noconfirm
```

Produces a one-dir build at `dist\MissionAutomation\` (deliberately
one-dir, not one-file - see the spec's own docstring for why). Verify
it launches: `dist\MissionAutomation\MissionAutomation.exe`.

## Bundled FFmpeg/FFprobe

`FFmpegCapabilityService._bundled_tool_path()` looks for
`tools\ffmpeg\ffmpeg.exe` / `ffprobe.exe` next to the built
`MissionAutomation.exe` and prefers them over PATH. This directory is
**not populated automatically** - a real, tested static Windows
ffmpeg/ffprobe build (e.g. from a trusted static-build provider) needs
to be placed at:

```
dist\MissionAutomation\tools\ffmpeg\ffmpeg.exe
dist\MissionAutomation\tools\ffmpeg\ffprobe.exe
```

before wrapping the build with the Inno Setup installer. Without it,
the app still works correctly - it falls back to PATH exactly like
today's development environment - just without the "every machine
uses the identical, tested FFmpeg version" guarantee the installer
plan calls for.

## Playwright Chromium

Not bundled - installed automatically the first time Google Flow
browser automation is actually used (see
`src/browser/chromium_bootstrap.py`). Nothing to do here.

## Not yet built

- `MissionAutomation.ico` (the spec has a commented-out `icon=`
  argument ready for it once one exists - today's icons are all
  runtime-rendered SVGs, see `src/desktop/icons.py`)
- The Inno Setup script that wraps `dist\MissionAutomation\` into
  `MissionAutomationSetup.exe`
