# Shop-server setup. The boot task runs as the local user eznest-svc with limited rights.
# That account is not an administrator. Its password stays in this process for task registration
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

# An installer launched from PowerShell 7 can inherit its incompatible modules.
# Administrative helpers use only the modules bundled with Windows PowerShell.
if ($PSVersionTable.PSVersion.Major -eq 5) {
  $env:PSModulePath = Join-Path $PSHOME 'Modules'
}

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
  # Domain-joined PCs often have an unresolvable SID in Administrators.
  # Listing that group then fails a retry after the account already exists.
  # Remove by name, and fail only when the account is still a member.
  try {
    Remove-LocalGroupMember -Group $admins.Name -Member $Name -ErrorAction Stop
  } catch {
    $notMember = $_.Exception.Message -match 'is not a member|No mapping between account names|cannot find|cannot be resolved'
    if (-not $notMember) {
      $stillAdmin = $false
      try {
        foreach ($member in @(Get-LocalGroupMember -Group $admins.Name -ErrorAction Stop)) {
          if ($member.SID -eq $accountSid) { $stillAdmin = $true }
        }
      } catch {
        throw "Could not confirm that $Name is outside Administrators. Shop setup stopped so the service account is not left as an administrator. $($_.Exception.Message)"
      }
      if ($stillAdmin) { throw "Could not remove $Name from Administrators." }
    }
  }
  $users = Get-LocalGroup -SID 'S-1-5-32-545'
  try {
    Add-LocalGroupMember -Group $users.Name -Member $Name -ErrorAction Stop
  } catch {
    if ($_.Exception.Message -notmatch 'already a member|already exists') {
      throw "Could not add $Name to Users. The shop service must be a normal local user. $($_.Exception.Message)"
    }
  }
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
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cfg)) {
    throw 'Windows could not export the user-rights policy, so eznest-svc cannot be granted batch logon. Shop setup stopped before creating the startup task.'
  }
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
    if ($at -lt 0) { throw 'Windows user-rights policy has no Privilege Rights section, so batch logon cannot be granted.' }
    $lines.Insert($at + 1, ('SeBatchLogonRight = ' + $marker))
  }
  $utf16 = New-Object System.Text.UnicodeEncoding $false, $true
  [System.IO.File]::WriteAllText($cfg, (($lines -join "`r`n") + "`r`n"), $utf16)
  & secedit.exe /configure /db $db /cfg $cfg /areas USER_RIGHTS /quiet | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "secedit could not apply batch logon (exit $LASTEXITCODE). Startup registration will still be attempted."
  }
  Remove-Item -LiteralPath $cfg, $db, ($db + '.jfm') -Force -ErrorAction SilentlyContinue
}

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$onyx = $OnyxPc -eq '1'
$lanEnabled = $Lan -eq '1'
$boot = $StartAtBoot -eq '1'
$updatesEnabled = $Updates -ne '0'
$utf8 = New-Object System.Text.UTF8Encoding $false
$shopPath = Join-Path $DataDir 'shop.json'
if (Test-Path -LiteralPath $shopPath) {
  $existing = Get-Content -Raw -LiteralPath $shopPath | ConvertFrom-Json
  $existing | Add-Member -NotePropertyName onyxPc -NotePropertyValue $onyx -Force
  $existing | Add-Member -NotePropertyName lan -NotePropertyValue $lanEnabled -Force
  $existing | Add-Member -NotePropertyName updates -NotePropertyValue $updatesEnabled -Force
  $shop = ($existing | ConvertTo-Json) + "`n"
} else {
  $shop = (@{
    onyxPc = $onyx
    lan = $lanEnabled
    updates = $updatesEnabled
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
if (Get-ScheduledTask -TaskName $task -TaskPath '\' -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $task -TaskPath '\' -Confirm:$false
}
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
  $launchArguments = '--web --no-browser --data-dir "' + $DataDir + '"'
  if ($lanEnabled) { $launchArguments += ' --lan' }
  $action = New-ScheduledTaskAction -Execute $App -Argument $launchArguments
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
  try {
    # Typed task fields preserve spaces in Program Files; no password is put
    # in a child process command line, script, or log.
    Register-ScheduledTask -TaskName $task -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -User $account -Password $password -RunLevel Limited -Force | Out-Null
  } finally { $password = $null }
}
& netsh.exe advfirewall firewall delete rule name=eznest | Out-Null
if ($lanEnabled) {
  & netsh.exe advfirewall firewall add rule name=eznest dir=in action=allow protocol=TCP localport=8765 profile=private
  if ($LASTEXITCODE -ne 0) { throw 'Could not open the shop-network port.' }
}
if ($boot) {
  $started = $false
  $startError = 'The startup task did not start.'
  foreach ($attempt in 1..5) {
    try {
      Start-ScheduledTask -TaskName $task -TaskPath '\'
      $started = $true
      break
    } catch {
      $startError = $_.Exception.Message
      if ($attempt -lt 5) { Start-Sleep -Seconds 2 }
    }
  }
  if (-not $started) {
    throw "The eznest startup task is registered but did not start ($startError). The limited account needs 'Log on as a batch job'. Sign out and back in, or restart this PC, then run the installer again."
  }
}


