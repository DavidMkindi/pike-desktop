; ===========================================================================
;  Pike - Inno Setup installer script
;
;  Wraps the PyInstaller one-file executable (dist\Pike.exe) into a proper
;  Windows setup program: Start Menu + optional desktop shortcut, Add/Remove
;  Programs entry, and a clean uninstaller.
;
;  Build it with:
;      iscc installer\pike.iss
;  or (recommended) run the helper:
;      python build_installer.py
;
;  AppVersion / AppPublisher / output paths come from build_installer.py which
;  passes them in via /D defines, so this file needs no editing to release.
; ===========================================================================

#define AppName "Pike"
#define AppExeName "Pike.exe"
#define AppId "{{4FFA2ED5-AD67-4D93-B06E-171ECD16FB41}"

; --- Defaults (overridable with /DAppVersion=... on the iscc command line) --
#ifndef AppVersion
  #define AppVersion "1.0.2"
#endif
#ifndef AppPublisher
  #define AppPublisher "Pike"
#endif
#ifndef AppUrl
  #define AppUrl "https://github.com/DavidMkindi/pike-desktop"
#endif
#ifndef SourceExe
  #define SourceExe "..\dist\Pike.exe"
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install so no administrator prompt is required.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=Pike-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\static\pike.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion
Source: "..\static\pike.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Interactive installs get the usual "Launch Pike" checkbox on the finish
; page. Silent installs (i.e. in-app updates) relaunch Pike automatically so
; the user is returned to the new version without doing anything.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall; Check: not WizardSilent
Filename: "{app}\{#AppExeName}"; Flags: nowait; Check: WizardSilent

[UninstallDelete]
; Per-user app data (settings + chat history) lives in %APPDATA%\Pike and is
; intentionally left in place so reinstalling keeps the user's data.
Type: dirifempty; Name: "{app}"