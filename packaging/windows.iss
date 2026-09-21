; Inno Setup script - wraps build\windows (see scripts/build_windows.py) into a per-user installer.
; Build: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows.iss
; Output: UsefulRedact-windows-x64-setup.exe in the repo root.

#define AppName "UsefulRedact"
#define AppVersion GetEnv("APP_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif

[Setup]
; Paths below are relative to the repo root, not to this file's folder.
SourceDir=..
AppId={{D5D8D4D6-C807-457B-BA21-2561C416C4CD}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Adam Simmons
AppPublisherURL=https://github.com/tuoa-tools/usefulredact
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=UsefulRedact-windows-x64-setup
SetupIconFile=packaging\icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
WizardStyle=modern

[Files]
Source: "build\windows\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "packaging\icon.ico"; DestDir: "{app}"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m app.launcher"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Comment: "Checks whether redaction holds"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m app.launcher"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m app.launcher"; WorkingDir: "{app}"; Description: "Open {#AppName} now"; Flags: postinstall nowait skipifsilent
