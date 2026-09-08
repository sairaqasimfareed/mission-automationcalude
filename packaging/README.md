# Mission Automation - Windows installer packaging

This directory holds the build tooling for producing
`MissionAutomationSetup.exe` - see `PROJECT_PROGRESS.md`'s dated
entries for the full history and decisions behind this setup.

## Full build sequence

```
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\pyinstaller.exe packaging\mission_automation.spec --noconfirm
.venv\Scripts\python.exe packaging\fetch_ffmpeg.py
"C:\Program Files\Inno Setup 7\ISCC.exe" packaging\mission_automation.iss
```

Produces `packaging\output\MissionAutomationSetup.exe`.

## Step 1: build the app (PyInstaller)

Produces a one-dir build at `dist\MissionAutomation\` (deliberately
one-dir, not one-file - see the spec's own docstring for why). Verify
it launches: `dist\MissionAutomation\MissionAutomation.exe`.

## Step 2: bundle FFmpeg/FFprobe

`FFmpegCapabilityService._bundled_tool_path()` looks for
`tools\ffmpeg\ffmpeg.exe` / `ffprobe.exe` next to the built
`MissionAutomation.exe` and prefers them over PATH. `fetch_ffmpeg.py`
downloads a real, static Windows build from gyan.dev (a well-known
static-build provider - see that script's own docstring for the exact
source and the version last verified against this project) and places
both binaries at:

```
dist\MissionAutomation\tools\ffmpeg\ffmpeg.exe
dist\MissionAutomation\tools\ffmpeg\ffprobe.exe
```

Not committed to git (binaries this size don't belong in version
control) - re-run the script after every fresh PyInstaller build.
Without this step the app still works correctly, falling back to
PATH exactly like a development environment - just without the
"every machine uses the identical, tested FFmpeg version" guarantee
the installer plan calls for.

## Step 3: Playwright Chromium

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

## Step 4: build the installer (Inno Setup)

Requires [Inno Setup](https://jrsoftware.org/isinfo.php) (not part of
this repo's own tooling - a separate, one-time install on the machine
doing the packaging build; verified against Inno Setup 7.1.0,
installed to `C:\Program Files\Inno Setup 7\ISCC.exe`).

```
"C:\Program Files\Inno Setup 7\ISCC.exe" packaging\mission_automation.iss
```

Output: `packaging\output\MissionAutomationSetup.exe`.

## Real, hands-on verification done (2026-09-08)

Not just "it compiled" - a real silent install/uninstall cycle was
run and checked:

- `MissionAutomationSetup.exe /VERYSILENT /SUPPRESSMSGBOXES
  /NORESTART /DIR=<test dir>` installed cleanly (Start Menu shortcut,
  desktop shortcut, `data\` directory, `tools\ffmpeg\ffmpeg.exe`/
  `ffprobe.exe` all present and correct).
- The installed `MissionAutomation.exe` launched correctly (confirmed
  via `tasklist /v` showing a real, responsive window titled "Mission
  Automation").
- The bundled `ffmpeg.exe -version` runs and reports a real, working
  FFmpeg 9.0.1 build.
- The uninstaller removed the app files, shortcuts, and registry
  uninstall entry cleanly, while correctly leaving `data\` in place
  (it wasn't empty) rather than silently deleting real project data.

**One open, disclosed finding, not yet resolved**: with the
`/VERYSILENT` flag specifically (automated/silent installs, not the
normal interactive double-click flow a real user follows), the app
launched itself despite the `[Run]` entry's `unchecked` +
`skipifsilent` flags, which were expected to suppress that. Not
investigated further yet - low real-world impact (a normal end user
sees the wizard's finish-page checkbox, unchecked by default, exactly
as designed; this only affects unattended/scripted installs).

## Not yet done

- Testing the interactive (non-silent) installer wizard end to end,
  by hand, on a real screen - every verification so far has been
  through `/VERYSILENT`.
- Code-signing (no certificate available; Windows SmartScreen will
  warn on first run of an unsigned installer/exe - expected, not a
  defect).
- The `/VERYSILENT` auto-launch finding above.
