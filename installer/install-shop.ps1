param(
  [Parameter(Mandatory = $true)][string]$DataDir,
  [Parameter(Mandatory = $true)][string]$App,
  [string]$OnyxPc = '0',
  [string]$Lan = '0',
  [string]$StartAtBoot = '0'
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$onyx = $OnyxPc -eq '1'
$lan = $Lan -eq '1'
$boot = $StartAtBoot -eq '1'
$utf8 = New-Object System.Text.UTF8Encoding $false
$shop = (@{ onyxPc = $onyx; lan = $lan } | ConvertTo-Json) + "`n"
[System.IO.File]::WriteAllText((Join-Path $DataDir 'shop.json'), $shop, $utf8)
if ($onyx) {
  $hot = 'C:\ONYX\EPSON SureColor S80600 ONYX Input'
  New-Item -ItemType Directory -Force -Path $hot | Out-Null
  $folder = (@{ path = $hot; configured = $true } | ConvertTo-Json) + "`n"
  [System.IO.File]::WriteAllText((Join-Path $DataDir 'output-folder.json'), $folder, $utf8)
}
$task = 'eznest'
& schtasks.exe /Delete /TN $task /F
if ($boot) {
  $cmd = Join-Path (Split-Path -Parent $App) 'eznest-server.cmd'
  & schtasks.exe /Create /TN $task /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "`"$cmd`"" /F
  if ($LASTEXITCODE -ne 0) { throw 'Could not register the eznest startup task.' }
}
& netsh.exe advfirewall firewall delete rule name=eznest
if ($lan) {
  & netsh.exe advfirewall firewall add rule name=eznest dir=in action=allow protocol=TCP localport=8765 profile=private
  if ($LASTEXITCODE -ne 0) { throw 'Could not open the shop-network port.' }
}
