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
function Invoke-SystemCommand([string]$Command) {
  # shop.json is limited to SYSTEM, Administrators, and eznest-svc. The runner
  # token cannot use the Administrators entry, so read and write through SYSTEM.
  $work = Join-Path $env:RUNNER_TEMP ('eznest-sys-' + [guid]::NewGuid().ToString('n'))
  New-Item -ItemType Directory -Path $work | Out-Null
  $stdout = Join-Path $work 'stdout.txt'
  $stderr = Join-Path $work 'stderr.txt'
  $code = @"
`$ErrorActionPreference = 'Stop'
try {
  & {
$Command
  } | Out-File -LiteralPath '$stdout' -Encoding utf8
  exit 0
} catch {
  `$_ | Out-File -LiteralPath '$stderr' -Encoding utf8
  exit 1
}
"@
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
  & icacls.exe $work /grant '*S-1-5-18:(OI)(CI)M' 'Users:(OI)(CI)M' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the SYSTEM acceptance helper.' }
  $task = 'eznest-sys-' + [guid]::NewGuid().ToString('n').Substring(0, 12)
  $shell = (Get-Process -Id $PID).Path
  $action = New-ScheduledTaskAction -Execute $shell -Argument "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Force | Out-Null
  try {
    Start-ScheduledTask -TaskName $task
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    $result = 267011
    do {
      Start-Sleep -Milliseconds 400
      $state = (Get-ScheduledTask -TaskName $task).State
      $result = (Get-ScheduledTaskInfo -TaskName $task).LastTaskResult
      # 267009 is still running. 267011 has not started yet.
      if ($state -ne 'Running' -and $state -ne 'Queued' -and $result -ne 267009 -and $result -ne 267011) { break }
    } while ([DateTime]::UtcNow -lt $deadline)
    $stillRunning = (Get-ScheduledTask -TaskName $task).State -eq 'Running'
    if ($stillRunning -or $result -ne 0) {
      $detail = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { '' }
      throw "Could not read the locked shop file as SYSTEM (result $result). $detail"
    }
  } finally {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
  }
  if (Test-Path -LiteralPath $stdout) { return (Get-Content -LiteralPath $stdout -Raw) }
  return ''
}
function Read-LockedFile([string]$Path) {
  return Invoke-SystemCommand "Get-Content -LiteralPath '$Path' -Raw"
}
function Get-LockedHash([string]$Path) {
  return (Invoke-SystemCommand "(Get-FileHash -LiteralPath '$Path' -Algorithm SHA256).Hash").Trim()
}
function Write-LockedFile([string]$Path, [string]$Text) {
  $src = Join-Path $env:RUNNER_TEMP ('eznest-marker-' + [guid]::NewGuid().ToString('n') + '.txt')
  [IO.File]::WriteAllText($src, $Text)
  & icacls.exe $src /grant '*S-1-5-18:(R)' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Could not grant SYSTEM read on the acceptance marker.' }
  Invoke-SystemCommand "Copy-Item -LiteralPath '$src' -Destination '$Path' -Force" | Out-Null
}
$setup = Join-Path $root 'installer\Output\eznest-setup.exe'
$setupLog = Join-Path $env:RUNNER_TEMP 'eznest-acceptance-install.log'
$install = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/TASKS="startatboot"',('/LOG="' + $setupLog + '"') -WindowStyle Hidden -PassThru
if (-not $install.WaitForExit(180000)) { throw 'Fresh installation timed out.' }
Get-Content -LiteralPath $setupLog -Tail 55
$shopFile = Join-Path $data 'shop.json'
Assert (Test-Path -LiteralPath $shopFile) 'Fresh install did not write shop.json.'
$acl = Invoke-SystemCommand "& icacls.exe '$shopFile'; if (`$LASTEXITCODE -ne 0) { throw 'icacls could not read the shop ACL' }"
Write-Output $acl
Assert ($acl -match 'SYSTEM' -and $acl -match 'Administrators' -and $acl -match 'eznest-svc') 'Shop data ACL is missing SYSTEM, Administrators, or eznest-svc.'
Assert ($acl -notmatch '\\Users:' -and $acl -notmatch 'Everyone') 'Shop data ACL is broader than SYSTEM, Administrators, and eznest-svc.'
Write-Output (Read-LockedFile $shopFile)
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
  Assert ($page.Content.Contains('id="files"') -and $page.Content.Contains('id="material"') -and $page.Content.Contains('id="export"')) 'Employee interface was not packaged.'
  $marker = Join-Path $data 'acceptance-marker.txt'
  Write-LockedFile $marker 'synthetic retained shop data'
  $beforeShop = Get-LockedHash $shopFile
  $beforeTask = Export-ScheduledTask -TaskName eznest
  Invoke-LocalApi '/api/shutdown' @{} | Out-Null
  Stop-ShopTask
  $reinstallLog = Join-Path $env:RUNNER_TEMP 'eznest-acceptance-reinstall.log'
  # Same-build maintenance install tests the existing-install path, not signed
  # version upgrade/rollback. Different task options must not reset the shop.
  $reinstall = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/EZUPDATE=1','/TASKS="startatboot,lan"',('/LOG="' + $reinstallLog + '"') -WindowStyle Hidden -PassThru
  if (-not $reinstall.WaitForExit(180000)) { throw 'Maintenance installation timed out.' }
  Get-Content -LiteralPath $reinstallLog -Tail 15
  Assert ($reinstall.ExitCode -eq 0) 'Existing-install detection failed.'
  Assert ((Get-LockedHash $shopFile) -eq $beforeShop) 'Maintenance install reset shop settings.'
  Enable-ScheduledTask -TaskName eznest | Out-Null
  Assert ((Export-ScheduledTask -TaskName eznest) -eq $beforeTask) 'Maintenance install changed the limited startup task.'
  Start-ScheduledTask -TaskName eznest
  Assert (Wait-ShopHealthy $version (Join-Path $app 'eznest.exe') 120) 'Maintenance installation did not restart.'
  $uninstall = Start-Process -FilePath (Join-Path $app 'unins000.exe') -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -PassThru
  if (-not $uninstall.WaitForExit(120000)) { throw 'Uninstall timed out.' }
  Assert ($uninstall.ExitCode -eq 0) 'Uninstall failed.'
  Assert (-not (Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue)) 'Uninstall left the startup task.'
  $account = Get-LocalUser -Name eznest-svc -ErrorAction SilentlyContinue
  Assert ($null -eq $account -or -not $account.Enabled) 'Uninstall left an enabled service account.'
  Assert ((Read-LockedFile $marker).Trim() -eq 'synthetic retained shop data') 'Uninstall removed shop data.'
  Write-Output 'Actual fresh install, limited service startup, loopback UI, maintenance reinstall/settings retention, and uninstall/data retention passed.'
} finally {
  # The hosted runner is destroyed after this job. Never recursively delete app/data here.
  $remaining = Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue
  if ($remaining) { Stop-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue }
}

