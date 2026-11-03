# Real installation, restricted to a disposable GitHub-hosted Windows runner.
# Run before test_installed_shop.ps1; no working shop PC may execute this file.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
  throw 'This acceptance test is restricted to disposable GitHub-hosted runners.'
}
$root = Split-Path -Parent $PSScriptRoot
$app = Join-Path $env:ProgramFiles 'eznest'
$shared = Join-Path $env:ProgramData 'eznest'
$localData = Join-Path $env:LOCALAPPDATA 'eznest-local'
if ((Test-Path -LiteralPath $app) -or (Test-Path -LiteralPath $shared) -or
    (Test-Path -LiteralPath $localData) -or
    (Get-LocalUser -Name 'eznest-svc' -ErrorAction SilentlyContinue) -or
    (Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue)) {
  throw 'Runner is not clean; refusing to change an existing installation.'
}
function Assert($value, $message) { if (-not $value) { throw $message } }
function Assert-NoShopService {
  Assert (-not (Test-Path -LiteralPath $shared)) 'Local installation touched ProgramData shop data.'
  Assert (-not (Get-LocalUser -Name 'eznest-svc' -ErrorAction SilentlyContinue)) 'Local installation created a service account.'
  Assert (-not (Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue)) 'Local installation created a startup task.'
  Assert (-not (Get-NetFirewallRule -DisplayName eznest -ErrorAction SilentlyContinue)) 'Local installation opened a firewall rule.'
}
$setup = Join-Path $root 'installer\Output\eznest-setup.exe'
function Install-Local([string]$Tasks, [string]$LogName) {
  $log = Join-Path $env:RUNNER_TEMP $LogName
  $process = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',("/TASKS=`"$Tasks`""),("/LOG=`"$log`"") -WindowStyle Hidden -PassThru
  if (-not $process.WaitForExit(180000)) { throw 'Local installer timed out.' }
  Assert ($process.ExitCode -eq 0) "Local installer failed; see $log"
  Assert-NoShopService
}
Install-Local 'desktopicon' 'eznest-local-fresh.log'
$exe = Join-Path $app 'eznest.exe'
Assert (Test-Path -LiteralPath $exe) 'The app was not installed.'
$shortcut = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'eznest.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
Assert ($link.Arguments -eq '--web --local-only') 'Shortcut must resolve per-user local data at runtime.'
$run = Start-Process -FilePath $exe -ArgumentList '--web','--local-only','--no-browser' -WindowStyle Hidden -PassThru
$session = $null
foreach ($attempt in 1..60) {
  try { $session = Invoke-RestMethod 'http://127.0.0.1:8765/api/session' -TimeoutSec 2; break } catch { Start-Sleep -Milliseconds 500 }
}
Assert ($session -and $session.app -eq 'eznest' -and $session.localDataId) 'Local app did not start with its own data identity.'
Assert (Test-Path -LiteralPath $localData) 'Local data folder was not created.'
$shop = Invoke-RestMethod 'http://127.0.0.1:8765/api/shop' -TimeoutSec 5
Assert (-not $shop.lan -and -not $shop.runningLan -and -not $shop.outputNetwork -and -not $shop.shareStockSummary) 'Local sharing must remain off.'
$repeat = Start-Process -FilePath $exe -ArgumentList '--web','--local-only','--no-browser' -WindowStyle Hidden -PassThru
Assert ($repeat.WaitForExit(15000) -and $repeat.ExitCode -eq 0) 'Reopening local mode should reuse the same host.'
$marker = Join-Path $localData 'acceptance-marker.txt'
[IO.File]::WriteAllText($marker, 'synthetic local stock marker')
Invoke-RestMethod 'http://127.0.0.1:8765/api/shutdown' -Method Post -ContentType 'application/json' -Body '{}' -Headers @{'X-EZ-Token'=$session.token} -TimeoutSec 10 | Out-Null
$session = $null
Assert ($run.WaitForExit(15000)) 'Local app did not stop normally.'
# An upgrade must retain local mode even if new task selections request a host.
Install-Local 'desktopicon,startatboot,lan' 'eznest-local-upgrade.log'
Assert ([IO.File]::ReadAllText($marker) -eq 'synthetic local stock marker') 'Upgrade changed local data.'
$link = $shell.CreateShortcut($shortcut)
Assert ($link.Arguments -eq '--web --local-only') 'Upgrade changed the data mode.'
$uninstaller = Join-Path $app 'unins000.exe'
$remove = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -PassThru
Assert ($remove.WaitForExit(60000) -and $remove.ExitCode -eq 0) 'Local uninstall failed.'
Assert (-not (Test-Path -LiteralPath $exe)) 'Local uninstall left the executable installed.'
Assert (-not (Test-Path -LiteralPath $app)) 'Local uninstall left the installation folder behind.'
Assert ([IO.File]::ReadAllText($marker) -eq 'synthetic local stock marker') 'Uninstall removed local data.'
Assert-NoShopService
Write-Output 'Local install, reopen, upgrade and uninstall passed; local data preserved and shop service absent.'
