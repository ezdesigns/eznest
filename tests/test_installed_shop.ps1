# Real system changes, ONLY on a disposable GitHub-hosted Windows runner.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
  throw 'This acceptance test is restricted to disposable GitHub-hosted runners. Never run on a shop PC.'
}
$root = Split-Path -Parent $PSScriptRoot
$app = Join-Path $env:ProgramFiles 'eznest'
$data = Join-Path $env:ProgramData 'eznest'
if ((Test-Path -LiteralPath $app) -or (Test-Path -LiteralPath $data) -or
    (Get-LocalUser -Name 'eznest-svc' -ErrorAction SilentlyContinue) -or
    (Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue)) {
  throw 'Runner is not clean; refusing to replace an existing shop installation.'
}
function Assert($value, $message) { if (-not $value) { throw $message } }
$setup = Join-Path $root 'installer\Output\eznest-setup.exe'
$setupLog = Join-Path $env:RUNNER_TEMP 'eznest-acceptance-install.log'
$install = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/TASKS="startatboot,noupdates"',('/LOG="' + $setupLog + '"') -WindowStyle Hidden -PassThru
if (-not $install.WaitForExit(180000)) { throw 'Fresh installation timed out.' }
Get-Content -LiteralPath $setupLog -Tail 55
if (Test-Path -LiteralPath (Join-Path $data 'shop.json')) {
  Get-Content -LiteralPath (Join-Path $data 'shop.json') -Raw
}
Assert ($install.ExitCode -eq 0) 'Fresh installer failed.'
try {
  $task = Get-ScheduledTask -TaskName eznest -ErrorAction Stop
  . (Join-Path $root 'installer/update-shop.ps1')
  Assert-ShopTask $task (Join-Path $app 'eznest.exe') $data
  Assert ($task.Actions[0].Arguments -notmatch '--lan') 'Fresh install enabled LAN.'
  $version = (Get-Content (Join-Path $root 'version.json') -Raw | ConvertFrom-Json).version
  Assert (Wait-ShopHealthy $version (Join-Path $app 'eznest.exe') 120) 'Installed server did not start as eznest-svc.'
  $shop = Invoke-RestMethod 'http://127.0.0.1:8765/api/shop'
  Assert (-not $shop.runningLan -and -not $shop.outputNetwork -and -not $shop.updates) 'Installed defaults differ from selected options.'
  $listeners = Get-NetTCPConnection -LocalPort 8765 -State Listen
  Assert (@($listeners | Where-Object LocalAddress -ne '127.0.0.1').Count -eq 0) 'Server opened a non-loopback listener.'
  $page = Invoke-WebRequest 'http://127.0.0.1:8765/web'
  Assert ($page.Content -match 'Job progress') 'Employee interface was not packaged.'
  [IO.File]::WriteAllText((Join-Path $data 'acceptance-marker.txt'), 'synthetic retained shop data')
  $uninstall = Start-Process -FilePath (Join-Path $app 'unins000.exe') -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -PassThru
  if (-not $uninstall.WaitForExit(120000)) { throw 'Uninstall timed out.' }
  Assert ($uninstall.ExitCode -eq 0) 'Uninstall failed.'
  Assert (-not (Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue)) 'Uninstall left the startup task.'
  $account = Get-LocalUser -Name eznest-svc -ErrorAction SilentlyContinue
  Assert ($null -eq $account -or -not $account.Enabled) 'Uninstall left an enabled service account.'
  Assert ((Get-Content (Join-Path $data 'acceptance-marker.txt') -Raw) -eq 'synthetic retained shop data') 'Uninstall removed shop data.'
  Write-Output 'Actual fresh install, limited service startup, loopback UI, and uninstall/data retention passed.'
} finally {
  # The hosted runner is destroyed after this job. Never recursively delete app/data here.
  $remaining = Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue
  if ($remaining) { Stop-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue }
}

