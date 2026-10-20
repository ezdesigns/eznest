$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../installer/update-shop.ps1')
function Assert($condition, $message) { if (-not $condition) { throw $message } }
function Reject([scriptblock]$body) {
  $rejected = $false
  try { & $body } catch { $rejected = $true }
  Assert $rejected 'Expected the operation to reject.'
}

Assert ((Compare-ReleaseVersion '1.0.0-rc.10' '1.0.0-rc.2') -gt 0) 'Numeric prerelease ordering failed.'
Assert ((Compare-ReleaseVersion '1.0.0' '1.0.0-rc.10') -gt 0) 'Stable must follow prerelease.'
Assert ((Compare-ReleaseVersion '0.9.9' '1.0.0') -lt 0) 'Downgrade ordering failed.'
Assert ((Compare-ReleaseVersion '1.0.0+build' '1.0.0') -eq 0) 'Build metadata changes precedence.'
Reject { Compare-ReleaseVersion 'bad' '1.0.0' }

function Get-AuthenticodeSignature { param($LiteralPath) return $script:signature }
$script:signature = @{ Status='Valid'; SignerCertificate=@{Thumbprint='trusted'} }
Assert-Publisher 'synthetic.exe' 'trusted'
Reject { Assert-Publisher 'synthetic.exe' 'other' }
$script:signature.Status = 'NotSigned'
Reject { Assert-Publisher 'synthetic.exe' 'trusted' }

function Get-LocalUser { param($Name, $ErrorAction) return @{SID='service-sid'} }
function Get-LocalGroup { param($SID) return @{Name='Administrators'} }
function Get-LocalGroupMember { param($Group) return @() }
$task = @{ Principal=@{UserId='eznest-svc';RunLevel='Limited'}; Settings=@{Enabled=$true}; Actions=@(@{Execute='C:\Program Files\eznest\eznest.exe'; Arguments='--web --no-browser --data-dir "C:\ProgramData\eznest" --lan'}) }
Assert-ShopTask $task 'C:\Program Files\eznest\eznest.exe' 'C:\ProgramData\eznest'
$task.Principal.UserId = 'SYSTEM'
Reject { Assert-ShopTask $task 'C:\Program Files\eznest\eznest.exe' 'C:\ProgramData\eznest' }

$script:taskCalls = New-Object 'System.Collections.Generic.List[string]'
function Get-ScheduledTask { param($TaskName, $TaskPath) return @{State=$script:taskState} }
function Disable-ScheduledTask { param($TaskName, $TaskPath) $script:taskCalls.Add('disable') }
function Stop-ScheduledTask { param($TaskName, $TaskPath) $script:taskCalls.Add('stop'); $script:taskState='Disabled' }
foreach ($state in @('Running', 'Queued', 'Ready')) {
  $script:taskState = $state; $script:taskCalls.Clear()
  Stop-ShopTask
  $expected = if ($state -eq 'Ready') { 'disable' } else { 'disable,stop' }
  Assert (($script:taskCalls -join ',') -eq $expected) 'Rollback must disable triggers and drain queued/running instances.'
}
$task.Principal.UserId = 'eznest-svc'; $task.Principal.RunLevel = 'Highest'
Reject { Assert-ShopTask $task 'C:\Program Files\eznest\eznest.exe' 'C:\ProgramData\eznest' }

# Exercise the actual transaction coordinator with synthetic files. No real
# installer, account, scheduled task, UAC prompt, firewall or hot folder is used.
$temp = Join-Path ([IO.Path]::GetTempPath()) ('eznest-helper-test-' + [guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
  $appFile = Join-Path $temp 'app.txt'; $dataFile = Join-Path $temp 'workload.sqlite3'
  [IO.File]::WriteAllText($appFile, 'old'); [IO.File]::WriteAllText($dataFile, 'tracking stays')
  $calls = New-Object 'System.Collections.Generic.List[string]'
  $install = { $calls.Add('install'); [IO.File]::WriteAllText($appFile, 'new') }
  $start = { $calls.Add('start') }
  $stop = { $calls.Add('stop') }
  $restore = { $calls.Add('restore'); [IO.File]::WriteAllText($appFile, 'old') }
  $result = Invoke-UpdateTransaction $install $start { $true } $stop $restore { $true }
  Assert $result.ok 'Successful update failed.'
  Assert (($calls -join ',') -eq 'install,start') 'Success unexpectedly stopped/restored.'
  $calls.Clear()
  $result = Invoke-UpdateTransaction $install $start { $false } $stop $restore { $true }
  Assert (-not $result.ok) 'Failed health must roll back.'
  Assert (($calls -join ',') -eq 'install,start,stop,restore,start') 'Rollback order is wrong.'
  Assert ((Get-Content -Raw -LiteralPath $appFile) -eq 'old') 'Old app not restored.'
  Assert ((Get-Content -Raw -LiteralPath $dataFile) -eq 'tracking stays') 'Tracking changed.'
  $calls.Clear()
  $result = Invoke-UpdateTransaction { throw 'setup failed' } $start { $true } $stop $restore { $true }
  Assert (-not $result.ok) 'Install failure must restore and restart.'
  Assert (($calls -join ',') -eq 'stop,restore,start') 'Install-failure recovery is wrong.'
  Reject { Invoke-UpdateTransaction $install $start { $false } $stop $restore { $false } }
} finally {
  $resolved = [IO.Path]::GetFullPath($temp)
  if (-not $resolved.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid test cleanup path.' }
  Remove-Item -LiteralPath $resolved -Recurse -Force
}
Write-Host 'Update helper tests passed: publisher, versions, limited task, install and rollback (system changes mocked).'
