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
  [string]$Updates = '0',
  # localsubnet, or the designer PCs' IPv4 addresses separated by commas.
  [string]$LanPeers = 'localsubnet',
  # Optional local HTTPS. Set both. The installer leaves HTTP when these are empty.
  [string]$TlsCert = '',
  [string]$TlsKey = ''
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

function Test-LanPeers([string]$Value) {
  if ($Value -eq 'localsubnet') { return $true }
  $parts = @($Value.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  if ($parts.Count -lt 1 -or $parts.Count -gt 16) { return $false }
  foreach ($part in $parts) {
    if ($part -notmatch '^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$') { return $false }
  }
  return $true
}

function Protect-DataDirectory([string]$Folder, [string]$Account) {
  # ProgramData lets Users create files. Remove that inheritance and keep
  # SYSTEM, Administrators, and the shop service account.
  # (OI)(CI) belongs on the directory so new children inherit it. Copying those
  # flags onto an existing file with /T and /grant:r leaves the file with no
  # effective access. Files get the same three principals without inherit-only flags.
  $inherit = @('SYSTEM:(OI)(CI)F', 'Administrators:(OI)(CI)F')
  $object = @('SYSTEM:F', 'Administrators:F')
  if ($Account) {
    $inherit += "${Account}:(OI)(CI)M"
    $object += "${Account}:M"
  }
  & icacls.exe $Folder /inheritance:r /grant:r @inherit
  if ($LASTEXITCODE -ne 0) { throw "Could not lock down $Folder to SYSTEM, Administrators, and the shop service account." }
  foreach ($child in @(Get-ChildItem -LiteralPath $Folder -Force -Recurse)) {
    $grant = if ($child.PSIsContainer) { $inherit } else { $object }
    & icacls.exe $child.FullName /inheritance:r /grant:r @grant
    if ($LASTEXITCODE -ne 0) { throw "Could not lock down $($child.FullName) to SYSTEM, Administrators, and the shop service account." }
  }
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
if (-not (Test-LanPeers $LanPeers)) {
  throw 'Designer PC addresses must be localsubnet or a comma-separated list of IPv4 addresses.'
}
if (($TlsCert -eq '') -ne ($TlsKey -eq '')) {
  throw 'Set both -TlsCert and -TlsKey, or leave both empty. HTTP stays the default.'
}
if ($TlsCert -match '[\r\n"]' -or $TlsKey -match '[\r\n"]') {
  throw 'TLS certificate paths cannot contain quotes or line breaks.'
}
$httpsLater = 'powershell -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -DataDir "' + $DataDir + '" -App "' + $App + '" -Lan ' + $Lan + ' -StartAtBoot ' + $StartAtBoot + ' -TlsCert C:\ProgramData\eznest\eznest-cert.pem -TlsKey C:\ProgramData\eznest\eznest-key.pem'
if (-not $TlsCert -and -not $TlsKey) {
  Write-Host ''
  Write-Host 'Recommended: use HTTPS so a PIN session cannot be copied from the shop network.'
  Write-Host 'This install keeps HTTP so setup does not stop.'
  Write-Host 'Before you enable it, create the certificate and run: icacls C:\ProgramData\eznest\eznest-key.pem /inheritance:r /grant:r *S-1-5-18:(R) *S-1-5-32-544:(R) eznest-svc:(R)'
  Write-Host 'To enable HTTPS later:'
  Write-Host ('  ' + $httpsLater)
  $ask = $env:EZ_NEST_HTTPS_PROMPT -eq '1'
  if (-not $ask -and $env:EZ_NEST_HTTPS_PROMPT -ne '0' -and $env:GITHUB_ACTIONS -ne 'true' -and $env:CI -ne 'true') {
    try { $ask = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected } catch { $ask = $false }
  }
  if ($ask) {
    $choice = Read-Host 'Press Enter to continue with HTTP, or type HTTPS to stop and use the command above'
    if ($choice -eq 'HTTPS') {
      throw 'Stopped before changing this PC. HTTP is still the default. Rerun with -TlsCert and -TlsKey when the key is restricted.'
    }
  }
}
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
  Protect-DataDirectory $DataDir $account
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
  if ($TlsCert -and $TlsKey) { $launchArguments += ' --tls-cert "' + $TlsCert + '" --tls-key "' + $TlsKey + '"' }
  $action = New-ScheduledTaskAction -Execute $App -Argument $launchArguments
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
  try {
    # Typed task fields preserve spaces in Program Files; no password is put
    # in a child process command line, script, or log.
    Register-ScheduledTask -TaskName $task -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -User $account -Password $password -RunLevel Limited -Force | Out-Null
  } finally { $password = $null }
} else {
  Protect-DataDirectory $DataDir ''
}
& netsh.exe advfirewall firewall delete rule name=eznest | Out-Null
if ($lanEnabled) {
  # Private profile only. remoteip defaults to this subnet, or the designer PCs passed in -LanPeers.
  & netsh.exe advfirewall firewall add rule name=eznest dir=in action=allow protocol=TCP localport=8765 profile=private "remoteip=$LanPeers"
  if ($LASTEXITCODE -ne 0) { throw 'Could not open the shop-network port.' }
  # The rule is Private-profile only. On a network Windows marks Public, other
  # PCs stay blocked; say so instead of changing the profile for the user.
  try {
    $public = @(Get-NetConnectionProfile -ErrorAction Stop | Where-Object { $_.NetworkCategory -eq 'Public' })
    if ($public.Count -gt 0) {
      Write-Warning ('This PC is on a network Windows marks Public (' + (($public | ForEach-Object { $_.Name }) -join ', ') + '). Other shop computers cannot reach eznest until an administrator sets the shop network to Private.')
    }
  } catch {}
  $pinFile = Join-Path $DataDir 'shop-pin.json'
  $pinReadable = $false
  if (Test-Path -LiteralPath $pinFile -PathType Leaf) {
    try {
      $pinData = Get-Content -LiteralPath $pinFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
      $pinReadable = [bool]($pinData -and $pinData.salt -and $pinData.hash -and ([string]$pinData.salt -match '^([0-9a-fA-F]{2})+$') -and ([string]$pinData.hash -match '^([0-9a-fA-F]{2})+$') -and ([int]$pinData.n -ge 4096) -and ([int]$pinData.n -le 32768) -and ([int]$pinData.r -eq 8) -and ([int]$pinData.p -eq 1))
    } catch { $pinReadable = $false }
    if (-not $pinReadable) {
      Write-Warning 'The shop PIN file is empty or damaged. eznest stays on this computer only until you set a new PIN at http://127.0.0.1:8765/web and restart it.'
    }
  } else {
    Write-Warning 'No shop PIN is set yet. eznest stays on this computer only until you set a PIN at http://127.0.0.1:8765/web and restart it.'
  }
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
Write-Host 'Connect this computer to OUTPUT before the shop nests.'
Write-Host 'Open http://127.0.0.1:8765/web and paste a pairing code from https://output.jeezlabs.io/outpost/ez-nest.'
Write-Host 'Activity sharing stays off until Enable sharing. This installer does not ask for or store a pairing code.'


