# Uninstall stops the eznest task, then removes the eznest-svc account and the
# folder permissions granted to it. If the account is still signed in, it is disabled.
# Shop files in the data folder are left on disk. The ONYX hot folder is left on disk.
param(
  [Parameter(Mandatory = $true)][string]$DataDir
)
$ErrorActionPreference = 'Continue'
$task = 'eznest'
$account = 'eznest-svc'
$hot = 'C:\ONYX\EPSON SureColor S80600 ONYX Input'

& schtasks.exe /End /TN $task | Out-Null
& schtasks.exe /Delete /TN $task /F | Out-Null

$user = Get-LocalUser -Name $account -ErrorAction SilentlyContinue
$sid = $null
if ($null -ne $user) { $sid = $user.SID.Value }

foreach ($folder in @($DataDir, $hot)) {
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
