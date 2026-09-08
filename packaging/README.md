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

## App icon

Already generated at `packaging\assets\mission_automation.ico` and
wired into the spec's `icon=` argument. Regenerate it (e.g. after
`app_icon()` itself changes) with:

```
QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe packaging\generate_app_icon.py
```

## Build the installer (Inno Setup)

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) (not
installed as part of this repo's own tooling - a separate,
one-time download on the machine doing the packaging build).

```
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\mission_automation.iss
```

Output: `packaging\output\MissionAutomationSetup.exe`. Build the
PyInstaller step first (`dist\MissionAutomation\` must already exist)
and place the bundled FFmpeg/FFprobe binaries under
`dist\MissionAutomation\tools\ffmpeg\` before compiling, if you want
them included.

**Not yet done**: an actual compiled `MissionAutomationSetup.exe` has
not been produced or run - `mission_automation.iss` has been authored
and reviewed but not compiled (this environment doesn't have Inno
Setup installed). Compiling it and running the resulting installer on
a real (or at least clean-ish) machine is the next real verification
step.
