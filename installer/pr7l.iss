; Paragon PR7-L installer (Inno Setup 6).
;   iscc /DAppVersion=0.1.0 installer\pr7l.iss      (after pyinstaller pr7l.spec has made dist\PR7-L)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-L, a Start menu entry and (ticked) "PR7-L"
; on Explorer's right-click menu for folders and audio files, as Mp3tag adds "Mp3tag".
; Registration is done by PR7-L itself (pr7l/shell.py); the uninstaller removes it again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{4C0E3F59-8A0B-4E7D-9B5A-2F7C61D3A9E1}
AppName=Paragon PR7-L
AppVersion={#AppVersion}
AppVerName=Paragon PR7-L {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-L
DefaultGroupName=Paragon PR7-L
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-L-Setup-{#AppVersion}
SetupIconFile=..\pr7l\icons\app.ico
UninstallDisplayIcon={app}\PR7-L.exe
UninstallDisplayName=Paragon PR7-L
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "contextmenu"; Description: "Add ""PR7-L"" to Explorer's right-click menu (folders and audio files)"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-L\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-L"; Filename: "{app}\PR7-L.exe"; Comment: "Tag editor"
Name: "{autodesktop}\Paragon PR7-L"; Filename: "{app}\PR7-L.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-L.exe"; Parameters: "--register"; Tasks: contextmenu; Flags: runhidden waituntilterminated; StatusMsg: "Adding ""PR7-L"" to Explorer..."
Filename: "{app}\PR7-L.exe"; Parameters: "--unregister"; Tasks: not contextmenu; Flags: runhidden waituntilterminated
Filename: "{app}\PR7-L.exe"; Description: "{cm:LaunchProgram,Paragon PR7-L}"; Flags: nowait postinstall skipifsilent
; Updates (Check for Updates runs this installer with /SILENT /relaunch=1): start PR7-L again when done.
Filename: "{app}\PR7-L.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[UninstallRun]
Filename: "{app}\PR7-L.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "PR7LUnregister"

[UninstallDelete]
; The file cache (pr7l/cache.py): only what PR7-L read from your files, nothing of yours.
Type: filesandordirs; Name: "{localappdata}\Paragon\PR7-L\cache"

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
