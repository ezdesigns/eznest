# Checks installer/install-shop.ps1 and installer/uninstall-shop.ps1.
# On Windows it also runs a boot-off install and the uninstall against a temp folder.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$install = Join-Path $root 'installer/install-shop.ps1'
$uninstall = Join-Path $root 'installer/uninstall-shop.ps1'

function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

function Assert-Parsed([string]$Path) {
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
  if ($errors -and $errors.Count -gt 0) {
    throw ($errors | ForEach-Object { $_.ToString() } | Out-String)
  }
}

Assert-Parsed $install
Assert-Parsed $uninstall

$installText = Get-Content -Raw -LiteralPath $install
$uninstallText = Get-Content -Raw -LiteralPath $uninstall
Assert-True ($installText.Contains('eznest-svc')) 'The installer must keep the eznest-svc account.'
Assert-True ($installText.Contains('/RL LIMITED')) 'The boot task must use limited rights.'
Assert-True (-not $installText.Contains('/RU SYSTEM')) 'The boot task must not run as SYSTEM.'
Assert-True (-not $installText.Contains('C:\ONYX\EPSON SureColor S80600 ONYX Input')) 'The installer must not hardcode the hot folder.'
Assert-True ($installText.Contains('setupComplete')) 'A fresh install waits for first-run setup.'
Assert-True ($installText.Contains('output-folder.json')) 'A saved hot folder can be granted on a later install.'
Assert-True ($uninstallText.Contains('eznest-svc')) 'Uninstall must remove the eznest-svc account.'
Assert-True ($uninstallText.Contains('output-folder.json')) 'Uninstall must read the saved hot folder.'
Assert-True (-not $uninstallText.Contains('C:\ONYX\EPSON SureColor S80600 ONYX Input')) 'Uninstall must not hardcode the hot folder.'
Assert-True ($uninstallText.IndexOf('/End') -lt $uninstallText.IndexOf('/Delete')) 'Uninstall stops the task before it deletes it.'
Assert-True ($uninstallText.IndexOf('Remove-LocalUser') -lt $uninstallText.IndexOf('Disable-LocalUser')) 'Uninstall removes the account, then disables it if that fails.'

$canRun = [bool](Get-Command schtasks.exe -ErrorAction SilentlyContinue) -and [bool](Get-Command netsh.exe -ErrorAction SilentlyContinue)
if (-not $canRun) {
  Write-Host 'Parsed the shop scripts. schtasks.exe is not on this machine, so the install was not run.'
  exit 0
}

$data = Join-Path ([System.IO.Path]::GetTempPath()) ('eznest-script-' + [guid]::NewGuid().ToString('n'))
$app = Join-Path $data 'app\eznest.exe'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $app) | Out-Null
New-Item -ItemType File -Force -Path $app | Out-Null
try {
  & $install -DataDir $data -App $app -OnyxPc '0' -Lan '0' -StartAtBoot '0' -Updates '1'
  $shop = Get-Content -Raw -LiteralPath (Join-Path $data 'shop.json') | ConvertFrom-Json
  Assert-True ($shop.onyxPc -eq $false) 'onyxPc stays off.'
  Assert-True ($shop.lan -eq $false) 'Shop network stays off.'
  Assert-True ($shop.updates -eq $true) 'Updates stay on.'
  Assert-True ($shop.channel -eq 'stable') 'The test channel stays off.'
  Assert-True ($shop.outputNetwork -eq $false) 'Join OUTPUT network stays off.'
  Assert-True ($shop.setupComplete -eq $false) 'The installer does not finish first-run setup.'
  Assert-True (-not (Test-Path -LiteralPath (Join-Path $data 'output-folder.json'))) 'The installer does not write a hot folder.'

  $hot = Join-Path $data 'hot'
  New-Item -ItemType Directory -Force -Path $hot | Out-Null
  @{ path = $hot; configured = $true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $data 'output-folder.json') -Encoding utf8
  & $uninstall -DataDir $data
  Assert-True (Test-Path -LiteralPath (Join-Path $data 'shop.json')) 'Uninstall leaves shop files on disk.'
  Assert-True (Test-Path -LiteralPath $hot) 'Uninstall leaves the hot folder on disk.'
} finally {
  Remove-Item -LiteralPath $data -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host 'Shop install scripts passed.'
