; AutoStream installer.
;
; WHY AN INSTALLER AT ALL
;   The app shipped as a 168 MB zip. Nothing else on Windows works that way, and
;   it caused real problems: no Start-menu entry, no uninstaller, and an upgrade
;   meant unzipping over a running program -- which leaves orphaned files from
;   the previous build behind, where they can shadow the new ones.
;
; PER-USER, NO ADMIN
;   PrivilegesRequired=lowest and an install under %LOCALAPPDATA%\Programs. This
;   app records the screen and talks to OBS on the user's own account; nothing
;   it does needs administrator, and asking for it would be the wrong signal.
;
; IT MUST NEVER TOUCH THE USER'S OWN FILES
;   Since 1.7.0 those live in %LOCALAPPDATA%\AutoStream, which is deliberately
;   NOT the install directory -- so uninstalling leaves settings, credentials
;   and logs alone, and reinstalling finds them again. Recordings and clips have
;   always lived in the user's Videos folder and are likewise untouched.
;
; SIGNING
;   Not signed here. SmartScreen will warn until a certificate exists; that is a
;   purchase, not a build step. When there is one, add SignTool= to this file
;   and the warning goes away as reputation builds.

#define AppName      "AutoStream"
#define AppPublisher "Hardik Sharma"
#define AppURL       "https://github.com/hardikneeravsharma/AutoStream"
#define AppExe       "AutoStream.exe"

; Passed in by scripts\build.ps1 so the version is never hand-edited here.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\AutoStream-share"
#endif

[Setup]
; Never change AppId: it is what makes an install an UPGRADE rather than a
; second copy sitting beside the first.
AppId={{8B1C4A6E-9F3D-4E27-A0B5-2C7D5E9A1F42}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}

DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\dist
OutputBaseFilename=AutoStream-{#AppVersion}-setup
SetupIconFile=..\autostream\ui\assets\autostream.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; The payload is already ~168 MB; showing what it is doing beats a frozen bar.
ShowLanguageDialog=no

; Shut the app down before replacing its files, and start it again afterwards.
; Without this an upgrade fails halfway on a locked exe and leaves a mixture of
; two builds on disk.
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=*.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start {#AppName} when I sign in"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
; The whole packaged folder. recursesubdirs picks up _internal, which is most
; of the payload.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} on GitHub"; Filename: "{#AppURL}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only what the PROGRAM created inside its own folder. The user's settings,
; credentials and logs are in %LOCALAPPDATA%\AutoStream and stay there; their
; recordings and clips are in Videos and stay there too.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
{ The same registry keys autostream\webview2.py checks, so the installer and
  the app can never disagree about whether the runtime is present. Without it
  the app falls back to opening its interface in a browser tab, which is the
  single thing that most makes it stop feeling like an application. }
const
  WV2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Present: Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WV2_GUID, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2_GUID, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2_GUID, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not WebView2Present then
      { Not fatal, and not a download the installer performs itself: the app
        already knows how to offer this, and a setup wizard that silently
        fetches 100 MB from Microsoft is worse than one that says so. }
      MsgBox('AutoStream draws its interface with the Microsoft Edge WebView2 '
             + 'runtime, which is not installed on this PC.'#13#10#13#10
             + 'AutoStream will still run and will offer to install it on '
             + 'first launch. Until then it opens in your browser instead of '
             + 'its own window.', mbInformation, MB_OK);
  end;
end;
