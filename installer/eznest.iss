; Shop-server installer. Build it on Windows: build_windows.py calls ISCC when Inno Setup 6 is present.
; Requires Inno Setup 6.3 or newer because shop setup uses ExecAndLogOutput.
; The Windows installer workflow uses 6.7.3. An older ISCC on PATH is not used when a newer compiler is installed.
; The shop PC runs eznest-setup.exe. It does not need Python or Git.

#ifndef SourceDir
  #define SourceDir "..\dist\eznest"
#endif

#define MyAppName "eznest"
#ifndef MyAppVersion
  #error MyAppVersion is passed from version.json by build_windows.py
#endif
#define MyAppPublisher "EZ Designs"

[Messages]
FinishedLabel=Setup has finished installing eznest on this computer.%n%nOpen eznest to start nesting. Connecting to OUTPUT is optional: choose Skip for local use. Sharing stays off until you enable it.

[Setup]
AppId={{A7E2C1D4-9B55-4E18-8C3A-6F0E2B9D4A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) 2026 EZ Designs
LicenseFile=..\LICENSE
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
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startatlogin"; Description: "Start Ez Nest when I sign in to Windows"; GroupDescription: "Automatic startup:"; Check: IsFreshInstall
Name: "startatboot"; Description: "Start eznest when Windows starts (shared shop host)"; GroupDescription: "Optional shop server; leave off for local use:"; Flags: unchecked
Name: "lan"; Description: "Shop network (other PCs on this network)"; GroupDescription: "Shop server:"; Flags: unchecked
Name: "onyxpc"; Description: "This PC runs ONYX"; GroupDescription: "Shop server:"; Flags: unchecked
Name: "checkupdates"; Description: "Check for app updates (also set EZ_NEST_UPDATES=1)"; GroupDescription: "Shop server:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "BUILD.json"
Source: "install-shop.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall-shop.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{src}\BUILD.json"; DestDir: "{app}"; Flags: external skipifsourcedoesntexist

[Icons]
Name: "{commondesktop}\eznest"; Filename: "{app}\eznest.exe"; Parameters: "{code:LaunchArguments}"; Tasks: desktopicon
Name: "{group}\eznest"; Filename: "{app}\eznest.exe"; Parameters: "{code:LaunchArguments}"
Name: "{group}\Stop eznest"; Filename: "{app}\Stop EZ Nest.cmd"
Name: "{group}\Update eznest"; Filename: "{app}\eznest.exe"; Parameters: "--request-shop-update"; Check: ServiceMode
; Common startup runs as the signed-in user, never the elevated installer account.
; Service hosts already have their own startup task and must not get a second host.
Name: "{commonstartup}\Ez Nest"; Filename: "{app}\eznest.exe"; Parameters: "--no-browser {code:LaunchArguments}"; WorkingDir: "{app}"; Check: StartAtLogin

[Registry]
Root: HKLM; Subkey: "Software\Classes\eznest-update"; ValueType: string; ValueData: "URL:eznest update"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\eznest-update"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKLM; Subkey: "Software\Classes\eznest-update\shell\open\command"; ValueType: string; ValueData: """{app}\eznest.exe"" --request-shop-update"

[Run]
Filename: "http://127.0.0.1:8765/web"; Description: "Open eznest"; Flags: shellexec postinstall skipifsilent; Check: OpenServicePage
Filename: "{app}\eznest.exe"; Parameters: "{code:LaunchArguments}"; Description: "Open eznest"; Flags: nowait postinstall skipifsilent; Check: OpenStandalonePage

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\uninstall-shop.ps1"" -DataDir ""{commonappdata}\eznest"""; Flags: runhidden waituntilterminated; RunOnceId: "UninstallShop"; Check: UninstallService

[Code]
var
  ExistingInstall: Boolean;
  ShopSetupFailed: Boolean;
  RetryShopSetup: Boolean;
  InstalledLocalMode: Boolean;
  InstalledStartAtLogin: Boolean;

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
  if WizardIsTaskSelected('checkupdates') then Result := '1' else Result := '0';
end;

function IsUpgrade: Boolean;
var
  Uninstall: String;
begin
  Result := RegQueryStringValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'UninstallString', Uninstall);
end;

function IsFreshInstall: Boolean;
begin
  Result := (not ExistingInstall) or RetryShopSetup;
end;

function LocalMode: Boolean;
begin
  if IsFreshInstall then Result := not WizardIsTaskSelected('startatboot')
  else Result := InstalledLocalMode;
end;

function LaunchArguments(Param: String): String;
begin
  if LocalMode then Result := '--web --local-only'
  else Result := '--web --data-dir "' + ExpandConstant('{commonappdata}\eznest') + '"';
end;

function ServiceMode: Boolean;
begin
  Result := not LocalMode;
end;

function StartAtLogin: Boolean;
begin
  if IsFreshInstall then
    Result := LocalMode and WizardIsTaskSelected('startatlogin')
  else
    { An update is not a new setup. Preserve an existing opt-out, including
      older releases which did not yet offer sign-in startup. }
    Result := InstalledLocalMode and InstalledStartAtLogin;
end;

function UninstallService: Boolean;
var
  Mode: Cardinal;
begin
  Result := not (RegQueryDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'LocalDataMode', Mode) and (Mode = 1));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and IsFreshInstall and LocalMode and
      (WizardIsTaskSelected('lan') or WizardIsTaskSelected('onyxpc') or WizardIsTaskSelected('checkupdates')) then
  begin
    MsgBox('Local use keeps shop network, ONYX setup, and automatic updates off. Clear those options, or select Start eznest when Windows starts to set up a shop host.', mbInformation, MB_OK);
    Result := False;
  end;
end;

function OpenServicePage: Boolean;
begin
  { Only fresh host setup guarantees a running service. Upgrades must launch
    the app so stopped/manual legacy installations also start. }
  Result := (not ShopSetupFailed) and (not LocalMode) and IsFreshInstall;
end;

function OpenStandalonePage: Boolean;
begin
  Result := (not ShopSetupFailed) and (not OpenServicePage);
end;

function InitializeSetup: Boolean;
var
  SetupComplete: Cardinal;
  LocalDataMode: Cardinal;
begin
  { Capture before Setup writes its own uninstall registration. }
  ExistingInstall := IsUpgrade;
  InstalledStartAtLogin := FileExists(ExpandConstant('{commonstartup}\Ez Nest.lnk'));
  InstalledLocalMode := RegQueryDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'LocalDataMode', LocalDataMode) and (LocalDataMode = 1);
  RetryShopSetup := RegQueryDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'ShopSetupComplete', SetupComplete) and (SetupComplete = 0);
  Log('Existing installation at start: ' + IntToStr(Ord(ExistingInstall)));
  Result := True;
  if ExpandConstant('{param:EZUPDATE|0}') = '1' then
  begin
    Result := ExistingInstall;
    if not Result then MsgBox('An existing eznest installation is required for this update.', mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Arguments: String;
begin
  if (CurStep = ssPostInstall) and IsFreshInstall then
  begin
    ShopSetupFailed := True;
    RegWriteDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'ShopSetupComplete', 0);
    if LocalMode then
    begin
      { Resolve the signed-in user's folder at runtime, not the elevated admin's.
        Do not call the service helper or touch existing ProgramData here. }
      RegWriteDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'LocalDataMode', 1);
      RegWriteDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'ShopSetupComplete', 1);
      ShopSetupFailed := False;
      Exit;
    end;
    RegWriteDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'LocalDataMode', 0);
    Log('Configuring fresh shop; selected tasks: ' + WizardSelectedTasks(False));
    Arguments := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install-shop.ps1') +
      '" -DataDir "' + ExpandConstant('{commonappdata}\eznest') + '" -App "' +
      ExpandConstant('{app}\eznest.exe') + '" -OnyxPc ' + OnyxFlag('') +
      ' -Lan ' + LanFlag('') + ' -StartAtBoot ' + BootFlag('') + ' -Updates ' + UpdatesFlag('');
    if not ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Arguments, '', SW_HIDE, ewWaitUntilTerminated, ResultCode, nil) then
      RaiseException('Windows could not start shop setup. Contact your shop administrator before using eznest.');
    if ResultCode <> 0 then
      RaiseException('Shop setup failed. The startup task or folder permissions need administrator attention. Do not use this installation for production yet.');
    RegWriteDWordValue(HKLM, ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'), 'ShopSetupComplete', 1);
    ShopSetupFailed := False;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if ShopSetupFailed then Result := 10 else Result := 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and ShopSetupFailed then
    WizardForm.FinishedLabel.Caption := 'Shop setup did not finish. Ask your administrator to review the startup task and folder permissions, then run this installer again. Do not use this installation for production yet.';
end;


