; Mission Automation - Inno Setup script
;
; Wraps a PyInstaller build (dist\MissionAutomation\, produced by
; packaging\mission_automation.spec - build that FIRST) into
; MissionAutomationSetup.exe. See packaging\README.md for the full
; build sequence and what still needs to be placed by hand before
; compiling this script (a real bundled FFmpeg/FFprobe under
; dist\MissionAutomation\tools\ffmpeg\).
;
; Compile with Inno Setup 6 (https://jrsoftware.org/isinfo.php):
;   ISCC.exe packaging\mission_automation.iss
; Output: packaging\output\MissionAutomationSetup.exe

#define MyAppName "Mission Automation"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Mission Automation"
#define MyAppExeName "MissionAutomation.exe"
#define MyDistDir "..\dist\MissionAutomation"

[Setup]
AppId={{6C6E1D2F-7B3A-4B0E-9C7F-1F5B7E2A9C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Real prerequisite checks (real disk space, memory) - Inno Setup's
; own [Setup] section handles disk space automatically via the real
; file list below; no separate hand-rolled check needed for that.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=MissionAutomationSetup
SetupIconFile=assets\mission_automation.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

; Real prerequisite check, matching the installer-bundle plan's own
; "performs prerequisite checks" step - refuses to proceed on an
; unsupported Windows version rather than installing into a broken
; state. Windows 10 is build 10240+; this uses Inno Setup's own
; documented MinVersion mechanism rather than a hand-rolled check.
MinVersion=10.0.10240

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Everything PyInstaller produced - the whole one-dir build,
; including tools\ffmpeg\ if it was placed there before compiling
; this script (see packaging\README.md).
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; "...launches Mission Automation" - the installer-bundle plan's own
; final step. Unticked by default so a silent/unattended install
; doesn't unexpectedly pop a window; the wizard's own finish-page
; checkbox lets an interactive install opt in.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked

[Dirs]
; "...creates application data folders" - the installer-bundle plan's
; own step. This app's own data/ layout (see src/desktop/services.py's
; PROVIDER_PROFILE_STORAGE_PATH and its sibling paths) is currently
; relative to the app's own working directory rather than a per-user
; profile location - created here as an empty, writable directory
; under the install root so the app's first real run has somewhere to
; write without needing elevated permissions beyond the install itself.
Name: "{app}\data"; Permissions: users-modify

[UninstallDelete]
; Uninstall must not silently delete a user's real generated projects/
; media (checkpoints, renders, provider secrets' own references) -
; only remove data\ if it is still genuinely empty. A non-empty data\
; is left in place; Inno Setup's own uninstaller reports this rather
; than forcing deletion.
Type: dirifempty; Name: "{app}\data"
