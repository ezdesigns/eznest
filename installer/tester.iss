; Separate per-user tester install. No shop service, account, firewall or protocol.
#ifndef SourceDir
  #error SourceDir must name a verified portable shop-trial folder
#endif
#ifndef MyAppVersion
  #error MyAppVersion must come from version.json
#endif
#ifndef BuildId
  #error BuildId must identify the tested package
#endif

[Setup]
AppId={{59A871A4-40D5-4B78-A37B-6B06E7B8613F}
AppName=EZ Nest Tester
AppVersion={#MyAppVersion}
AppVerName=EZ Nest Tester {#MyAppVersion} ({#BuildId})
AppPublisher=EZ Designs TX
DefaultDirName={localappdata}\Programs\EZ Nest Tester\{#BuildId}
UsePreviousAppDir=no
DefaultGroupName=EZ Nest Tester
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputBaseFilename=EZ-Nest-Tester-{#BuildId}-Setup
SetupIconFile=..\assets\eznest.ico
UninstallDisplayIcon={app}\app\eznest.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\EZ Nest Tester"; Filename: "{app}\app\eznest.exe"; Parameters: "--shop-test"
Name: "{group}\EZ Nest Tester"; Filename: "{app}\app\eznest.exe"; Parameters: "--shop-test"
Name: "{group}\Stop EZ Nest Tester"; Filename: "{app}\STOP Shop Test.cmd"
Name: "{group}\EZ Nest test guide"; Filename: "{app}\READ FIRST.txt"

[Run]
Filename: "{app}\app\eznest.exe"; Parameters: "--shop-test"; Description: "Open EZ Nest Tester"; Flags: nowait postinstall skipifsilent

; App data and exported customer files are deliberately outside {app} and are
; never removed by this installer or its uninstaller.
