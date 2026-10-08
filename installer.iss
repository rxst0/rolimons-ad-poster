; Inno Setup script: builds dist\RolimonsAdPosterSetup.exe
; Per-user install (no admin prompt) to %LOCALAPPDATA%\Programs\Rolimons Ad Poster,
; with a Start Menu entry (so Windows Search finds it), optional desktop icon and an uninstaller.

#define AppName "Rolimons Ad Poster"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{7C1E5B2A-4F3D-4C8E-9A61-2B7D0E5F3A91}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=rxst0
AppPublisherURL=https://github.com/rxst0/rolimons-ad-poster
AppSupportURL=https://github.com/rxst0/rolimons-ad-poster/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=RolimonsAdPosterSetup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\RoliAdPoster.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\RoliAdPoster.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\RoliAdPoster.exe"; Comment: "Auto-post Rolimons trade ads"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\RoliAdPoster.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RoliAdPoster.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files the app creates at runtime (including the saved cookie).
Type: files; Name: "{app}\.env"
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\config.json.tmp"
Type: files; Name: "{app}\state.json"
Type: filesandordirs; Name: "{app}\logs"
