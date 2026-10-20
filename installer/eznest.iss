; Shop-server installer. Build it on Windows: build_windows.py calls ISCC when Inno Setup 6 is present.
; The shop PC runs eznest-setup.exe. It does not need Python or Git.

#ifndef SourceDir
  #define SourceDir "..\dist\eznest"
#endif

#define MyAppName "eznest"
#ifndef MyAppVersion
  #error MyAppVersion is passed from version.json by build_windows.py
#endif
#define MyAppPublisher "EZ Designs TX"

[Setup]
AppId={{A7E2C1D4-9B55-4E18-8C3A-6F0E2B9D4A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\eznest
DefaultGroupName=eznest
DisableProgramGroupPage=no
OutputDir=Output
OutputBaseFilename=eznest-setup
SetupIconFile=..\assets\eznest.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayIcon={app}\eznest.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startatboot"; Description: "Start eznest when Windows starts"; GroupDescription: "Shop server:"; Flags: checkedonce
Name: "lan"; Description: "Shop network (other PCs on this network)"; GroupDescription: "Shop server:"; Flags: unchecked
Name: "onyxpc"; Description: "This PC runs ONYX"; GroupDescription: "Shop server:"; Flags: unchecked
Name: "noupdates"; Description: "Disable updates (offline install)"; GroupDescription: "Shop server:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "BUILD.json"
Source: "install-shop.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall-shop.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{src}\BUILD.json"; DestDir: "{app}"; Flags: external skipifsourcedoesntexist

[Icons]
Name: "{commondesktop}\eznest"; Filename: "{app}\eznest.exe"; Parameters: "--web --data-dir ""{commonappdata}\eznest"""; Tasks: desktopicon
Name: "{group}\eznest"; Filename: "{app}\eznest.exe"; Parameters: "--web --data-dir ""{commonappdata}\eznest"""
Name: "{group}\Stop eznest"; Filename: "{app}\Stop EZ Nest.cmd"
Name: "{group}\Update eznest"; Filename: "{app}\eznest.exe"; Parameters: "--request-shop-update"

[Registry]
Root: HKLM; Subkey: "Software\Classes\eznest-update"; ValueType: string; ValueData: "URL:eznest update"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\eznest-update"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKLM; Subkey: "Software\Classes\eznest-update\shell\open\command"; ValueType: string; ValueData: """{app}\eznest.exe"" --request-shop-update"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-shop.ps1"" -DataDir ""{commonappdata}\eznest"" -App ""{app}\eznest.exe"" -OnyxPc {code:OnyxFlag} -Lan {code:LanFlag} -StartAtBoot {code:BootFlag} -Updates {code:UpdatesFlag}"; Flags: runhidden waituntilterminated; Check: IsFreshInstall
Filename: "{app}\eznest.exe"; Parameters: "--web --data-dir ""{commonappdata}\eznest"""; Description: "Open eznest"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-shop.ps1"" -DataDir ""{commonappdata}\eznest"""; Flags: runhidden waituntilterminated; RunOnceId: "UninstallShop"

[Code]
function OnyxFlag(Param: String): String;
begin
  if WizardIsTaskSelected('onyxpc') then Result := '1' else Result := '0';
end;

function LanFlag(Param: String): String;
begin
  if WizardIsTaskSelected('lan') then Result := '1' else Result := '0';
end;

function BootFlag(Param: String): String;
begin
  if WizardIsTaskSelected('startatboot') then Result := '1' else Result := '0';
end;

function UpdatesFlag(Param: String): String;
begin
  if WizardIsTaskSelected('noupdates') then Result := '0' else Result := '1';
end;

function IsUpgrade: Boolean;
var
  Uninstall: String;
begin
  Result := RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1', 'UninstallString', Uninstall);
end;

function IsFreshInstall: Boolean;
begin
  Result := not IsUpgrade;
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if ExpandConstant('{param:EZUPDATE|0}') = '1' then
  begin
    Result := IsUpgrade;
    if not Result then MsgBox('An existing eznest installation is required for this update.', mbError, MB_OK);
  end;
end;

