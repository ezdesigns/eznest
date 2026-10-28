# Pure coordinator tests: HTTP, CIM and sleeping are synthetic on every OS.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../installer/update-shop.ps1')

function Invoke-RestMethod {
  param($Uri, $TimeoutSec, [switch]$UseBasicParsing)
  $script:sample = $script:samples[$script:polls]
  $script:polls++
  if ($script:sample.error) { throw 'Synthetic connection failure' }
  return @{ app='eznest'; version=$script:sample.version; pid=$script:sample.id; token='synthetic' }
}
function Get-CimInstance {
  param($ClassName, $Filter)
  return @{ ProcessId=$script:sample.id; CreationDate=$script:sample.created; ExecutablePath='synthetic-app' }
}
function Invoke-CimMethod {
  param($InputObject, $MethodName)
  return @{ User=$script:sample.owner; Domain=$env:COMPUTERNAME }
}
function Start-Sleep {
  param($Seconds)
  if ($script:polls -ge $script:samples.Count) { throw 'SYNTHETIC_POLL_LIMIT' }
}
function Sample($id=41, $created='2026-01-01T00:00:00Z', $version='1.1.0', $owner='eznest-svc') {
  return @{ id=$id; created=$created; version=$version; owner=$owner }
}
function Check-Health($name, [object[]]$values, [bool]$expected, [int]$polls) {
  $script:samples=$values; $script:polls=0
  try { $actual = Wait-ShopHealthy '1.1.0' 'synthetic-app' 30 }
  catch {
    if ($_.Exception.Message -ne 'SYNTHETIC_POLL_LIMIT') { throw }
    $actual = $false
  }
  if ($actual -ne $expected -or $script:polls -ne $polls) {
    throw "$name`: health=$actual, polls=$script:polls; expected health=$expected, polls=$polls"
  }
  Write-Host "PASS: $name"
}

Check-Health 'stable process' @((Sample), (Sample), (Sample)) $true 3
Check-Health 'crash loop never becomes healthy' @((Sample 41), (Sample 42), (Sample 43)) $false 3
Check-Health 'restart resets consecutive responses' @((Sample 41), (Sample 42), (Sample 42), (Sample 42)) $true 4
Check-Health 'reused PID is a different process' @((Sample), (Sample 41 'later'), (Sample 41 'latest')) $false 3
Check-Health 'missing creation identity fails closed' @((Sample 41 $null), (Sample 41 $null), (Sample 41 $null)) $false 3
Check-Health 'invalid PID fails closed' @((Sample 0), (Sample 0), (Sample 0)) $false 3
Check-Health 'failed request resets evidence' @((Sample), @{error=$true}, (Sample), (Sample), (Sample)) $true 5
Check-Health 'wrong version resets evidence' @((Sample), (Sample 41 '2026-01-01T00:00:00Z' 'old'), (Sample), (Sample), (Sample)) $true 5
Check-Health 'wrong service account fails closed' @((Sample 41 'same' '1.1.0' 'admin'), (Sample 41 'same' '1.1.0' 'admin'), (Sample 41 'same' '1.1.0' 'admin')) $false 3
$script:polls=0
if ((Wait-ShopHealthy '1.1.0' 'synthetic-app' 0) -or $script:polls -ne 0) { throw 'Expired health deadline queried the service.' }
Write-Host 'PASS: expired deadline'
