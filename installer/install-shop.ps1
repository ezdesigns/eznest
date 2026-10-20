# Shop-server setup. The boot task runs as the local user eznest-svc with limited rights.
# That account is not an administrator. Its password stays in this process for schtasks
# and is not written into the eznest folder. The account can read and write the data
# folder. When a hot folder is already saved and it is on this PC, the account
# can write that folder too. The path is chosen on first run, not here.
param(
  [Parameter(Mandatory = $true)][string]$DataDir,
  [Parameter(Mandatory = $true)][string]$App,
  [string]$OnyxPc = '0',
  [string]$Lan = '0',
  [string]$StartAtBoot = '0',
  [string]$Updates = '1'
)

function New-ServicePassword {
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $sets = @(
    'ABCDEFGHJKLMNPQRSTUVWXYZ'.ToCharArray(),
    'abcdefghijkmnopqrstuvwxyz'.ToCharArray(),
    '23456789'.ToCharArray(),
    '#+='.ToCharArray()
  )
  $chars = New-Object System.Collections.Generic.List[char]
  foreach ($set in $sets) {
    $bytes = New-Object byte[] 6
    $rng.GetBytes($bytes)
    for ($i = 0; $i -lt $bytes.Length; $i++) { [void]$chars.Add($set[$bytes[$i] % $set.Length]) }
  }
  $order = New-Object byte[] $chars.Count
  $rng.GetBytes($order)
  $ranked = for ($i = 0; $i -lt $chars.Count; $i++) { '{0:D3}{1}' -f $order[$i], [string]$chars[$i] }
  return -join ($ranked | Sort-Object | ForEach-Object { $_.Substring(3) })
}

function Ensure-ServiceAccount([string]$Name) {
  $password = New-ServicePassword
  $secure = ConvertTo-SecureString -String $password -AsPlainText -Force
  $user = Get-LocalUser -Name $Name -ErrorAction SilentlyContinue
  if ($null -eq $user) {
    New-LocalUser -Name $Name -Password $secure -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires -Description 'eznest shop server. No administrator rights.' | Out-Null
  } else {
    Set-LocalUser -Name $Name -Password $secure -PasswordNeverExpires $true
    if (-not $user.Enabled) { Enable-LocalUser -Name $Name }
  }
  $accountSid = (Get-LocalUser -Name $Name).SID
  $admins = Get-LocalGroup -SID 'S-1-5-32-544'
  try {
    $adminMembers = @(Get-LocalGroupMember -Group $admins.Name -ErrorAction Stop)
  } catch {
    if ($null -ne $user) { throw }
    $adminMembers = @()
  }
  foreach ($member in $adminMembers) {
    if ($member.SID -eq $accountSid) {
      Remove-LocalGroupMember -Group $admins.Name -Member $Name
    }
  }
  $users = Get-LocalGroup -SID 'S-1-5-32-545'
  $inUsers = $false
  foreach ($member in @(Get-LocalGroupMember -Group $users.Name -ErrorAction SilentlyContinue)) {
    if ($member.SID -eq $accountSid) { $inUsers = $true }
  }
  if (-not $inUsers) { Add-LocalGroupMember -Group $users.Name -Member $Name -ErrorAction SilentlyContinue }
  return $password
}

function Grant-Folder([string]$Account, [string]$Folder, [string]$Rights) {
  & icacls.exe $Folder /grant "${Account}:${Rights}" /T
  if ($LASTEXITCODE -ne 0) { throw "Could not grant $Account permission on $Folder." }
}

function Grant-BatchLogon([string]$Account) {
  $sid = (New-Object System.Security.Principal.NTAccount($Account)).Translate([System.Security.Principal.SecurityIdentifier]).Value
  $cfg = Join-Path $env:TEMP ('eznest-rights-' + [guid]::NewGuid().ToString('n') + '.inf')
  $db = Join-Path $env:TEMP ('eznest-rights-' + [guid]::NewGuid().ToString('n') + '.sdb')
  & secedit.exe /export /cfg $cfg /areas USER_RIGHTS /quiet | Out-Null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cfg)) { return }
  $lines = New-Object System.Collections.Generic.List[string]
  foreach ($line in [System.IO.File]::ReadAllLines($cfg)) { [void]$lines.Add($line) }
  $marker = '*' + $sid
  $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].StartsWith('SeBatchLogonRight')) {
      $found = $true
      if ($lines[$i].IndexOf($marker) -lt 0) { $lines[$i] = $lines[$i].TrimEnd() + ',' + $marker }
    }
  }
  if (-not $found) {
    $at = $lines.IndexOf('[Privilege Rights]')
    if ($at -lt 0) { return }
    $lines.Insert($at + 1, ('SeBatchLogonRight = ' + $marker))
  }
  $utf16 = New-Object System.Text.UnicodeEncoding $false, $true
  [System.IO.File]::WriteAllText($cfg, (($lines -join "`r`n") + "`r`n"), $utf16)
  & secedit.exe /configure /db $db /cfg $cfg /areas USER_RIGHTS /quiet | Out-Null
  Remove-Item -LiteralPath $cfg, $db, ($db + '.jfm') -Force -ErrorAction SilentlyContinue
}

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$onyx = $OnyxPc -eq '1'
$lan = $Lan -eq '1'
$boot = $StartAtBoot -eq '1'
$updates = $Updates -ne '0'
$utf8 = New-Object System.Text.UTF8Encoding $false
$shopPath = Join-Path $DataDir 'shop.json'
if (Test-Path -LiteralPath $shopPath) {
  $existing = Get-Content -Raw -LiteralPath $shopPath | ConvertFrom-Json
  $existing | Add-Member -NotePropertyName onyxPc -NotePropertyValue $onyx -Force
  $existing | Add-Member -NotePropertyName lan -NotePropertyValue $lan -Force
  $existing | Add-Member -NotePropertyName updates -NotePropertyValue $updates -Force
  $shop = ($existing | ConvertTo-Json) + "`n"
} else {
  $shop = (@{
    onyxPc = $onyx
    lan = $lan
    updates = $updates
    channel = 'stable'
    outputNetwork = $false
    setupComplete = $false
    printer = ''
    units = 'in'
    thru = ''
    kiss = ''
    hotFolder = ''
  } | ConvertTo-Json) + "`n"
}
[System.IO.File]::WriteAllText($shopPath, $shop, $utf8)
$task = 'eznest'
$account = 'eznest-svc'
& schtasks.exe /Delete /TN $task /F | Out-Null
if ($boot) {
  $password = Ensure-ServiceAccount $account
  Grant-Folder $account $DataDir '(OI)(CI)M'
  $savedHot = Join-Path $DataDir 'output-folder.json'
  if (Test-Path -LiteralPath $savedHot) {
    try {
      $configured = Get-Content -Raw -LiteralPath $savedHot | ConvertFrom-Json
      $hot = [string]$configured.path
      if ($hot -and -not $hot.StartsWith('\\') -and (Test-Path -LiteralPath $hot -PathType Container)) {
        Grant-Folder $account $hot '(OI)(CI)W'
      }
    } catch {}
  }
  Grant-BatchLogon $account
  $cmd = Join-Path (Split-Path -Parent $App) 'eznest-server.cmd'
  & schtasks.exe /Create /TN $task /SC ONSTART /RU $account /RP $password /RL LIMITED /TR "`"$cmd`"" /F *> $null
  $password = $null
  if ($LASTEXITCODE -ne 0) { throw 'Could not register the eznest startup task.' }
}
& netsh.exe advfirewall firewall delete rule name=eznest | Out-Null
if ($lan) {
  & netsh.exe advfirewall firewall add rule name=eznest dir=in action=allow protocol=TCP localport=8765 profile=private
  if ($LASTEXITCODE -ne 0) { throw 'Could not open the shop-network port.' }
}
