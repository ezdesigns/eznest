# Interactive, administrator-approved helper. The app is restarted only through
# the existing limited eznest-svc task. No server or downloaded script is elevated.
param([switch]$Run)

function Assert-NoLinks([string]$Path) {
  $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
  while ($null -ne $item) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked update paths are not supported.' }
    $item = if ($item.PSIsContainer) { $item.Parent } else { $item.Directory }
  }
}

function Assert-AppTree([string]$Root) {
  Assert-NoLinks $Root
  foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'The application contains a linked path.' }
  }
}

function Assert-Publisher([string]$File, [string]$Thumbprint) {
  $signature = Get-AuthenticodeSignature -LiteralPath $File
  if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
      $signature.SignerCertificate.Thumbprint -ne $Thumbprint) {
    throw 'The update publisher signature is missing, invalid or different. The current app was kept.'
  }
}

function Compare-ReleaseVersion([string]$Left, [string]$Right) {
  $pattern = '^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$'
  $a = [regex]::Match($Left, $pattern); $b = [regex]::Match($Right, $pattern)
  if (-not $a.Success -or -not $b.Success) { throw 'Invalid release version.' }
  for ($i = 1; $i -le 3; $i++) {
    $order = ([long]$a.Groups[$i].Value).CompareTo([long]$b.Groups[$i].Value)
    if ($order -ne 0) { return $order }
  }
  $ap = $a.Groups[4].Value; $bp = $b.Groups[4].Value
  if (-not $ap -and -not $bp) { return 0 }
  if (-not $ap) { return 1 }; if (-not $bp) { return -1 }
  $aa = $ap.Split('.'); $bb = $bp.Split('.')
  for ($i = 0; $i -lt [Math]::Min($aa.Count, $bb.Count); $i++) {
    if ($aa[$i] -match '^\d+$' -and $bb[$i] -match '^\d+$') { $order = ([long]$aa[$i]).CompareTo([long]$bb[$i]) }
    elseif ($aa[$i] -match '^\d+$') { $order = -1 }
    elseif ($bb[$i] -match '^\d+$') { $order = 1 }
    else { $order = [String]::CompareOrdinal($aa[$i], $bb[$i]) }
    if ($order -ne 0) { return $order }
  }
  return $aa.Count.CompareTo($bb.Count)
}

function Assert-ShopTask([object]$Task, [string]$App, [string]$Data, [bool]$RequireEnabled = $true) {
  $service = Get-LocalUser -Name 'eznest-svc' -ErrorAction Stop
  $identity = [string]$Task.Principal.UserId
  if ($identity -notin @('eznest-svc', "$env:COMPUTERNAME\eznest-svc", [string]$service.SID) -or
      [string]$Task.Principal.RunLevel -notin @('Limited', '0')) { throw 'The eznest task must use limited eznest-svc rights.' }
  if (@($Task.Actions).Count -ne 1 -or [IO.Path]::GetFullPath($Task.Actions[0].Execute) -ne $App) {
    throw 'The eznest startup task points to a different application.'
  }
  $expected = '--web --no-browser --data-dir "' + $Data + '"'
  if ([string]$Task.Actions[0].Arguments -notin @($expected, ($expected + ' --lan'))) {
    throw 'The startup task arguments need review before updating.'
  }
  if ($RequireEnabled -and -not $Task.Settings.Enabled) { throw 'Enable the existing eznest startup task before updating.' }
  $admins = Get-LocalGroup -SID 'S-1-5-32-544'
  if (@(Get-LocalGroupMember -Group $admins.Name | Where-Object { $_.SID -eq $service.SID }).Count) {
    throw 'eznest-svc must not be an administrator.'
  }
}

function Invoke-LocalApi([string]$Path, [object]$Body = $null) {
  $args = @{ Uri = ('http://127.0.0.1:8765' + $Path); TimeoutSec = 180; UseBasicParsing = $true }
  if ($null -ne $Body) {
    $args.Method = 'Post'; $args.ContentType = 'application/json'
    $args.Headers = @{ 'X-EZ-Token' = $script:SessionToken }
    $args.Body = ConvertTo-Json -InputObject $Body -Compress
  }
  return Invoke-RestMethod @args
}

function Wait-ShopHealthy([string]$Version, [string]$App, [int]$Seconds = 120) {
  $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
  $consecutive = 0
  while ([DateTime]::UtcNow -lt $deadline) {
    try {
      $session = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/session' -TimeoutSec 3 -UseBasicParsing
      $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$session.pid)
      $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner
      if ($session.app -eq 'eznest' -and $session.version -eq $Version -and
          $process.ExecutablePath -eq $App -and $owner.User -eq 'eznest-svc' -and $owner.Domain -eq $env:COMPUTERNAME) {
        $consecutive++
        if ($consecutive -ge 3) { $script:SessionToken = $session.token; return $true }
      } else { $consecutive = 0 }
    } catch { $consecutive = 0 }
    Start-Sleep -Seconds 2
  }
  return $false
}

function Invoke-UpdateTransaction([scriptblock]$Install, [scriptblock]$Start,
    [scriptblock]$Healthy, [scriptblock]$Stop, [scriptblock]$Restore,
    [scriptblock]$OldHealthy) {
  try {
    & $Install
    & $Start
    if (-not (& $Healthy)) { throw 'The new version did not become healthy.' }
    return @{ ok = $true; message = 'Update installed. Settings and local activity were kept.' }
  } catch {
    $failure = $_.Exception.Message
    & $Stop
    & $Restore
    & $Start
    if (-not (& $OldHealthy)) { throw 'The previous files were restored, but eznest did not restart. Contact the shop administrator.' }
    return @{ ok = $false; message = ('The previous version was restored. ' + $failure) }
  }
}

function Invoke-ShopUpdate {
  $ErrorActionPreference = 'Stop'
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Windows administrator approval is required.' }
  $root = [IO.Path]::GetFullPath($PSScriptRoot)
  $programs = [Environment]::GetFolderPath('ProgramFiles')
  if (-not $root.StartsWith($programs.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use the helper installed in Program Files.'
  }
  Assert-AppTree $root
  $data = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'eznest'
  Assert-NoLinks $data
  $app = Join-Path $root 'eznest.exe'
  $task = Get-ScheduledTask -TaskName 'eznest' -TaskPath '\' -ErrorAction Stop
  Assert-ShopTask $task $app $data
  $publisher = (Get-Content -LiteralPath (Join-Path $root 'update-publisher.txt') -Raw).Trim()
  if ($publisher -notmatch '^[0-9A-Fa-f]{40}$') { throw 'No trusted update publisher is configured.' }
  Assert-Publisher $app $publisher
  $previous = (Get-Content -LiteralPath (Join-Path $root 'version.json') -Raw | ConvertFrom-Json).version
  $pendingPath = Join-Path $data 'updates\pending.json'
  Assert-NoLinks $pendingPath
  $pending = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
  if (-not $pending.verified -or $pending.filename -ne 'eznest-setup.exe' -or
      $pending.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $pending.version -notmatch '^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$') {
    throw 'Download a checked installer in eznest first.'
  }
  $incoming = Join-Path $data 'updates\incoming\eznest-setup.exe'
  if ((Compare-ReleaseVersion $pending.version $previous) -le 0) { throw 'The update must be newer than the installed version.' }
  if ([IO.Path]::GetFullPath($pending.file) -ne $incoming) { throw 'The staged installer path is invalid.' }
  Assert-NoLinks $incoming
  # A fresh directory under Program Files inherits administrator-only write
  # access. Recheck copied bytes here, not a mutable service-account path.
  $private = Join-Path $programs ('eznest-update-' + [guid]::NewGuid().ToString('n'))
  New-Item -ItemType Directory -Path $private -ErrorAction Stop | Out-Null
  $setup = Join-Path $private 'eznest-setup.exe'
  $backup = Join-Path $private 'previous'
  $claimed = $false; $disabled = $false; $complete = $false
  $flags = @{ replacing = $false }
  try {
    Copy-Item -LiteralPath $incoming -Destination $setup
    if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash -ne $pending.sha256) { throw 'The installer checksum changed.' }
    Assert-Publisher $setup $publisher
    $session = Invoke-LocalApi '/api/session'
    if ($session.app -ne 'eznest' -or $session.version -ne $previous) { throw 'Start the installed eznest version first.' }
    $script:SessionToken = $session.token
    $ticket = [guid]::NewGuid().ToString('n')
    $request = @{ ticket = $ticket; sha256 = $pending.sha256 }
    Invoke-LocalApi '/api/update/queue' $request | Out-Null
    $deadline = [DateTime]::UtcNow.AddHours(12)
    do {
      if ([DateTime]::UtcNow -ge $deadline) { throw 'Update waiting timed out. The app stays running.' }
      Invoke-LocalApi '/api/state' | Out-Null
      $claim = Invoke-LocalApi '/api/update/claim' $request
      if (-not $claim.ready) { Start-Sleep -Seconds 2 }
    } while (-not $claim.ready)
    $claimed = $true
    # Prevent a task trigger during replacement; retain its account, credentials,
    # arguments (including explicit --lan), triggers and settings unchanged.
    Disable-ScheduledTask -TaskName 'eznest' -TaskPath '\' | Out-Null
    $disabled = $true
    $process = Get-Process -Id ([int]$claim.pid) -ErrorAction SilentlyContinue
    if ($process) { if (-not $process.WaitForExit(30000)) { throw 'The app did not close. No files were replaced.' } }
    Assert-AppTree $root
    Copy-Item -LiteralPath $root -Destination $backup -Recurse
    $install = {
      $flags.replacing = $true
      $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/EZUPDATE=1', ('/DIR="' + $root + '"'))
      $installer = Start-Process -FilePath $setup -ArgumentList $arguments -WindowStyle Hidden -PassThru
      if (-not $installer.WaitForExit(600000)) {
        $installer.Kill(); $installer.WaitForExit()
        throw 'The installer timed out.'
      }
      if ($installer.ExitCode -ne 0) { throw 'The installer did not finish.' }
      $version = (Get-Content -LiteralPath (Join-Path $root 'version.json') -Raw | ConvertFrom-Json).version
      if ($version -ne $pending.version) { throw 'The installed version does not match the checked release.' }
      Assert-Publisher $app $publisher
      Assert-ShopTask (Get-ScheduledTask -TaskName 'eznest' -TaskPath '\') $app $data $false
    }
    $start = {
      Enable-ScheduledTask -TaskName 'eznest' -TaskPath '\' | Out-Null
      Start-ScheduledTask -TaskName 'eznest' -TaskPath '\'
    }
    $stop = {
      Stop-ScheduledTask -TaskName 'eznest' -TaskPath '\'
      $deadlineStop = [DateTime]::UtcNow.AddSeconds(30)
      while ((Get-ScheduledTask -TaskName 'eznest' -TaskPath '\').State -eq 'Running') {
        if ([DateTime]::UtcNow -ge $deadlineStop) { throw 'Could not stop the failed version. Backup retained for recovery.' }
        Start-Sleep -Milliseconds 200
      }
    }
    $restore = {
      # Both locations were resolved beneath Program Files; reject linked trees
      # again immediately before recursive replacement. Never clear the data dir.
      Assert-AppTree $root; Assert-AppTree $backup
      Get-ChildItem -LiteralPath $root -Force | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
      Get-ChildItem -LiteralPath $backup -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $root -Recurse -Force }
      $uninstall = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A7E2C1D4-9B55-4E18-8C3A-6F0E2B9D4A11}_is1'
      Set-ItemProperty -LiteralPath $uninstall -Name DisplayVersion -Value $previous
    }
    $result = Invoke-UpdateTransaction $install $start { Wait-ShopHealthy $pending.version $app } $stop $restore { Wait-ShopHealthy $previous $app }
    $disabled = $false; $complete = $true
    Invoke-LocalApi '/api/update/result' @{ sha256 = $pending.sha256; message = $result.message } | Out-Null
    return $result.message
  } finally {
    if ($disabled) { Enable-ScheduledTask -TaskName 'eznest' -TaskPath '\' | Out-Null }
    if ($claimed -and -not $complete -and -not $flags.replacing) { Start-ScheduledTask -TaskName 'eznest' -TaskPath '\' }
    if ($complete -or -not $claimed) {
      Assert-AppTree $private
      Remove-Item -LiteralPath $private -Recurse -Force
    }
    # On an interrupted transaction retain the protected backup for recovery.
  }
}

if ($Run) {
  $mutex = New-Object Threading.Mutex($false, 'Global\eznest-interactive-update')
  $held = $false
  try {
    $held = $mutex.WaitOne(0)
    if (-not $held) { throw 'Another update helper is already open.' }
    $message = Invoke-ShopUpdate
  } catch { $message = $_.Exception.Message }
  finally { if ($held) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
  Add-Type -AssemblyName System.Windows.Forms
  [Windows.Forms.MessageBox]::Show($message, 'eznest update') | Out-Null
}
