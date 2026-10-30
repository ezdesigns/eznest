# Only the published, hash-pinned installer runs the application. No source-mode
# auth bypass, customer files, telemetry consent, or production shop is used.
# Connect needs a short-lived owner-approved test-shop code in a GitHub secret.
# The controller must revoke the reported host in OUTPUT, including after failure.
param([ValidateSet('Connect', 'VerifyRevoked', 'Cleanup')][string]$Phase = 'Connect')
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or -not $IsWindows) {
  throw 'Only a disposable GitHub-hosted Windows runner may run this acceptance test.'
}
$app = Join-Path $env:ProgramFiles 'eznest'
$data = Join-Path $env:ProgramData 'eznest'
$receiptPath = Join-Path $env:RUNNER_TEMP 'eznest-output-acceptance.json'
$ownedMarker = Join-Path $env:RUNNER_TEMP 'eznest-output-acceptance-owned'
$setup = Join-Path $env:RUNNER_TEMP 'eznest-public-setup.exe'
$version = '1.0.0-rc.5'
$expectedHash = '05e25fddebc78b57057d9b0fb4246307d8195537b56b51f06a7d7ab51d0a0889'
. (Join-Path $PSScriptRoot '../installer/update-shop.ps1')
$script:assertionFailure = ''
function Assert($condition, [string]$message) {
  if (-not $condition) { $script:assertionFailure = $message; throw $message }
}
function Save-Receipt($receipt) { $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath }
function Api([string]$path, $body = $null) {
  $request = @{
    Uri = "http://127.0.0.1:8765$path"; TimeoutSec = 30
    SkipHttpErrorCheck = $true
  }
  if ($script:SessionToken) { $request.Headers = @{ 'X-EZ-Token' = $script:SessionToken } }
  if ($null -ne $body) {
    $request.Method = 'Post'; $request.ContentType = 'application/json'
    $request.Body = ConvertTo-Json -InputObject $body -Depth 15 -Compress
  }
  $response = Invoke-WebRequest @request
  return @{ Status = [int]$response.StatusCode; Json = ($response.Content | ConvertFrom-Json) }
}
function Session {
  $response = Api '/api/session'
  Assert ($response.Status -eq 200 -and $response.Json.version -eq $version) 'Unexpected installed server session.'
  $script:SessionToken = $response.Json.token
  Assert (-not [string]::IsNullOrWhiteSpace($script:SessionToken)) 'Local session token is missing.'
  Write-Host "::add-mask::$script:SessionToken"
  return $response.Json
}
function Read-CheckinTime {
  # The installed service owns this protected file. Read only the successful
  # check-in timestamp as SYSTEM; never expose the credential, HMAC or raw file.
  $work = Join-Path $env:RUNNER_TEMP ('eznest-checkin-' + [guid]::NewGuid().ToString('n'))
  New-Item -ItemType Directory -Path $work | Out-Null
  $runnerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  & icacls.exe $work /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' "*${runnerSid}:(OI)(CI)F" | Out-Null
  Assert ($LASTEXITCODE -eq 0) 'Could not prepare the restricted check-in reader.'
  $output = Join-Path $work 'last-ok.txt'
  $statePath = Join-Path $data 'output-checkin.json'
  $command = "`$ErrorActionPreference='Stop'; `$state=Get-Content -LiteralPath '$statePath' -Raw | ConvertFrom-Json; [long]`$state.lastOkAt | Set-Content -LiteralPath '$output'; exit 0"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
  $taskName = 'eznest-checkin-' + [guid]::NewGuid().ToString('n')
  $action = New-ScheduledTaskAction -Execute (Get-Process -Id $PID).Path -Argument "-NoProfile -EncodedCommand $encoded"
  $principal = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal | Out-Null
  try {
    Start-ScheduledTask -TaskName $taskName
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
      Start-Sleep -Milliseconds 300
      $info = Get-ScheduledTaskInfo -TaskName $taskName
      $taskState = (Get-ScheduledTask -TaskName $taskName).State
      if ($taskState -notin @('Running','Queued') -and $info.LastTaskResult -notin @(267009,267011)) { break }
    } while ([DateTime]::UtcNow -lt $deadline)
    Assert ($taskState -notin @('Running','Queued') -and $info.LastTaskResult -eq 0 -and (Test-Path $output)) 'Could not read successful check-in time.'
    return [long](Get-Content -LiteralPath $output -Raw).Trim()
  } finally {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  }
}
function Stop-OwnedInstaller {
  # The preflight/marker owns only this temporary installer's exact path.
  foreach ($process in Get-Process -ErrorAction SilentlyContinue) {
    if ($process.Path -eq $setup) {
      $process.Kill($true)
      Assert ($process.WaitForExit(30000)) 'Owned installer did not stop.'
    }
  }
  Assert (-not @(Get-Process -ErrorAction SilentlyContinue | Where-Object Path -eq $setup).Count) 'Owned installer is still running.'
}
try {
  if ($Phase -eq 'Cleanup') {
    # A failed clean-run preflight never gives us ownership of an existing shop.
    if (-not (Test-Path -LiteralPath $ownedMarker)) { exit 0 }
    Stop-OwnedInstaller
    $uninstaller = Join-Path $app 'unins000.exe'
    try {
      $null = Session
      $null = Api '/api/telemetry/output/disconnect' @{}
    } catch { } # Remote revocation is independently checked through the owner UI.
    if (Test-Path -LiteralPath $uninstaller) {
      $uninstall = Start-Process $uninstaller -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -PassThru
      Assert ($uninstall.WaitForExit(120000) -and $uninstall.ExitCode -eq 0) 'Acceptance uninstall failed.'
    }
    $remaining = Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue
    if ($remaining) { Stop-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue }
    Assert (-not $remaining) 'Uninstall left the shop task.'
    $service = Get-LocalUser -Name eznest-svc -ErrorAction SilentlyContinue
    Assert ($null -eq $service -or -not $service.Enabled) 'Uninstall left an enabled service account.'
    if (Test-Path -LiteralPath $receiptPath) {
      $receipt = Get-Content $receiptPath -Raw | ConvertFrom-Json -AsHashtable
      $receipt.cleanup = $true; Save-Receipt $receipt
    }
    exit 0
  }
  if ($Phase -eq 'Connect') {
    Assert ($env:EZ_NEST_ACCEPTANCE_CODE -match '^[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}$') 'A valid owner-approved test-shop pairing secret is required.'
    Assert (-not ((Test-Path $app) -or (Test-Path $data) -or
      (Get-LocalUser -Name eznest-svc -ErrorAction SilentlyContinue) -or
      (Get-ScheduledTask -TaskName eznest -ErrorAction SilentlyContinue))) 'Runner already has a shop; refusing to change it.'
    New-Item -ItemType File -Path $ownedMarker | Out-Null
    $receipt = @{ version=$version; sha256=$expectedHash; runId=$env:GITHUB_RUN_ID; hostLabel=$env:COMPUTERNAME; paired=$false; restarted=$false; nested=$false; sharingOff=$false; revoked=$false; cleanup=$false }
    Save-Receipt $receipt
    Invoke-WebRequest -Uri 'https://github.com/ezdesigns/eznest/releases/download/v1.0.0-rc.5/eznest-setup.exe' -OutFile $setup
    Assert ((Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedHash) 'Public installer hash mismatch.'
    $install = Start-Process $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/TASKS="startatboot"' -PassThru
    if (-not $install.WaitForExit(180000)) {
      Stop-OwnedInstaller
      throw 'Owned public installer timed out and was stopped.'
    }
    Assert ($install.ExitCode -eq 0) 'Public installer failed.'
    $task = Get-ScheduledTask -TaskName eznest
    Assert-ShopTask $task (Join-Path $app 'eznest.exe') $data
    Assert ($task.Actions[0].Arguments -notmatch '--lan') 'Installer enabled LAN.'
    Assert (Wait-ShopHealthy $version (Join-Path $app 'eznest.exe') 120) 'Installed limited service did not become healthy.'
    $session = Session
    Assert (-not $session.outputConnection.ok -and -not $session.outputConnection.devMode) 'Fresh installed connection status should be unpaired.'
    Assert ((Api '/api/state').Status -eq 200) 'Unpaired installed workspace was blocked.'
    $paired = Api '/api/telemetry/output/pair' @{code=$env:EZ_NEST_ACCEPTANCE_CODE}
    Assert ($paired.Status -eq 200 -and $paired.Json.configured -and -not $paired.Json.enabled) 'Installed host did not pair with sharing off.'
    $receipt.paired = $true; Save-Receipt $receipt
    $reused = Api '/api/telemetry/output/pair' @{code=$env:EZ_NEST_ACCEPTANCE_CODE}
    Assert ($reused.Status -eq 400 -and $reused.Json.reason -eq 'consumed') 'Used pairing code was not rejected.'
    $env:EZ_NEST_ACCEPTANCE_CODE = $null
    $pairedAt = Read-CheckinTime
    Start-Sleep -Seconds 2
    $check = Api '/api/telemetry/output/check-in' @{}
    $checkedAt = Read-CheckinTime
    Assert ($check.Status -eq 200 -and $check.Json.ok -and $checkedAt -gt $pairedAt) 'Production check-in did not advance successful time.'
    $receipt.checkedInAt = $checkedAt
    $before = (Session).pid
    Stop-ShopTask
    Start-Sleep -Seconds 2
    Enable-ScheduledTask -TaskName eznest | Out-Null
    Start-ScheduledTask -TaskName eznest
    Assert (Wait-ShopHealthy $version (Join-Path $app 'eznest.exe') 120) 'Service restart failed.'
    $session = Session
    $check = Api '/api/telemetry/output/check-in' @{}
    $restartedAt = Read-CheckinTime
    Assert ($session.pid -ne $before -and $check.Status -eq 200 -and $check.Json.ok -and -not $check.Json.devMode -and $restartedAt -gt $checkedAt) 'Stored service credential did not complete a new check-in after restart.'
    $receipt.restartCheckedInAt = $restartedAt
    $receipt.restarted = $true
    $sharing = Api '/api/telemetry/output'
    Assert ($sharing.Status -eq 200 -and $sharing.Json.configured -and -not $sharing.Json.enabled) 'Activity sharing unexpectedly enabled.'
    $receipt.sharingOff = $true
    $job = '{"parts":[{"id":"synthetic-square","quantity":2,"points":[[0,0],[20,0],[20,20],[0,20]]}],"settings":{"width":100,"gap":2,"margin":2,"seconds":1,"rotations":[0],"seed":42}}' | ConvertFrom-Json
    Assert ((Api '/api/solve' $job).Status -eq 200) 'Installed nesting did not start.'
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do { Start-Sleep -Seconds 1; $state = Api '/api/state' } while ($state.Json.status -eq 'running' -and [DateTime]::UtcNow -lt $deadline)
    Assert ($state.Status -eq 200 -and $state.Json.status -eq 'ready' -and @($state.Json.result.placements).Count -eq 2) 'Installed nesting did not finish two synthetic pieces.'
    $receipt.nested = $true; Save-Receipt $receipt
    Write-Output 'CONNECT_PASS: public installed service paired, checked in, restarted, nested; sharing remains off. Owner must now revoke the reported host.'
  } else {
    $receipt = Get-Content $receiptPath -Raw | ConvertFrom-Json -AsHashtable
    Assert ($receipt.paired -and $receipt.restarted -and $receipt.nested) 'Connect evidence is incomplete.'
    $null = Session
    # OUTPUT allows 8 check-ins per source address per 15 minutes. Connect uses
    # three (including service startup); reserve at most four more here. Give
    # the controller time to read the artifact and revoke before the first call.
    Start-Sleep -Seconds 60
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
      $check = Api '/api/telemetry/output/check-in' @{}
      if ($check.Status -eq 200 -and $check.Json.state -eq 'revoked' -and -not $check.Json.ok) { break }
      if ($attempt -lt 3) { Start-Sleep -Seconds 120 }
    }
    Assert ($check.Status -eq 200 -and $check.Json.state -eq 'revoked' -and -not $check.Json.ok) 'Owner revocation was not observed within the bounded check-in budget.'
    Assert ((Api '/api/state').Status -eq 200) 'Revoked OUTPUT connection blocked the installed workspace.'
    Assert ((Api '/api/solve' @{}).Status -eq 400) 'Revoked installed host did not validate the empty nesting request.'
    $receipt.revoked = $true; Save-Receipt $receipt
    Write-Output 'REVOCATION_PASS: production revocation was reported; the installed API remains accessible.'
  }
} catch {
  # Never emit exception/request/session bodies; they can contain credentials.
  Write-Error "Published Windows OUTPUT acceptance failed in phase $Phase. $script:assertionFailure Inspect sanitized receipt and the owner host list; revoke any created test host."
  exit 1
}
