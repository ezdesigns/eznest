; Shop-server installer. Build it on Windows: build_windows.py calls ISCC when Inno Setup 6 is present.
; The shop PC runs eznest-setup.exe. It does not need Python or Git.

#ifndef SourceDir
  #define SourceDir "..\dist\eznest"
#endif

#define MyAppName "eznest"
#define MyAppVersion "1.0.0-rc.1"
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

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install-shop.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{commondesktop}\eznest"; Filename: "{app}\eznest.exe"; Parameters: "--web --data-dir ""{commonappdata}\eznest"""; Tasks: desktopicon
Name: "{group}\eznest"; Filename: "{app}\eznest.exe"; Parameters: "--web --data-dir ""{commonappdata}\eznest"""
Name: "{group}\Stop eznest"; Filename: "{app}\Stop EZ Nest.cmd"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-shop.ps1"" -DataDir ""{commonappdata}\eznest"" -App ""{app}\eznest.exe"" -OnyxPc {code:OnyxFlag} -Lan {code:LanFlag} -StartAtBoot {code:BootFlag}"; Flags: runhidden waituntilterminated
Filename: "{app}\eznest.exe"; Parameters: "--web --data-dir ""{commonappdata}\eznest"""; Description: "Open eznest"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /TN eznest /F"; Flags: runhidden; RunOnceId: "DelTask"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=eznest"; Flags: runhidden; RunOnceId: "DelFw"

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
