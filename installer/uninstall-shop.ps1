# Uninstall stops the eznest task, then removes the eznest-svc account and the
# folder permissions granted to it. If the account is still signed in, it is disabled.
# Shop files in the data folder are left on disk. A saved hot folder is left on disk.
param(
  [Parameter(Mandatory = $true)][string]$DataDir
)
$ErrorActionPreference = 'Continue'
$task = 'eznest'
$account = 'eznest-svc'
$folders = New-Object System.Collections.Generic.List[string]
[void]$folders.Add($DataDir)
$savedHot = Join-Path $DataDir 'output-folder.json'
if (Test-Path -LiteralPath $savedHot) {
  try {
    $configured = Get-Content -Raw -LiteralPath $savedHot | ConvertFrom-Json
    $hot = [string]$configured.path
    if ($hot -and -not $hot.StartsWith('\\')) { [void]$folders.Add($hot) }
  } catch {}
}

& schtasks.exe /End /TN $task | Out-Null
& schtasks.exe /Delete /TN $task /F | Out-Null

$user = Get-LocalUser -Name $account -ErrorAction SilentlyContinue
$sid = $null
if ($null -ne $user) { $sid = $user.SID.Value }

foreach ($folder in $folders) {
  if (-not (Test-Path -LiteralPath $folder)) { continue }
  & icacls.exe $folder /remove $account /T /C | Out-Null
  if ($sid) { & icacls.exe $folder /remove "*$sid" /T /C | Out-Null }
}

if ($null -ne $user) {
  if ($sid) {
    $profiles = @(Get-CimInstance -ClassName Win32_UserProfile -Filter "SID='$sid'" -ErrorAction SilentlyContinue)
    foreach ($profile in $profiles) {
      if ($null -ne $profile -and -not $profile.Loaded) {
        Remove-CimInstance -InputObject $profile -ErrorAction SilentlyContinue
      }
    }
  }
  try {
    Remove-LocalUser -Name $account -ErrorAction Stop
  } catch {
    Disable-LocalUser -Name $account -ErrorAction SilentlyContinue
  }
}

& netsh.exe advfirewall firewall delete rule name=eznest | Out-Null
