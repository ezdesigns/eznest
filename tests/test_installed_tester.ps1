# Real install/uninstall, ONLY on a disposable GitHub-hosted Windows runner.
param([string]$Setup, [string]$TrialPackage, [string]$BuildId, [string]$ReportDir)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Installed-tester acceptance is restricted to disposable GitHub-hosted runners. Never run on a shop or design PC.'
}
function Assert($value, $message) { if (-not $value) { throw $message } }
Assert ($BuildId -match '^ci-[0-9]+-[0-9]+$') 'Expected a unique CI build ID.'
$setupFile = (Resolve-Path -LiteralPath $Setup).Path
$package = (Resolve-Path -LiteralPath $TrialPackage).Path
$report = [IO.Path]::GetFullPath($ReportDir)
$runnerRoot = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\') + '\'
Assert ($report.StartsWith($runnerRoot, [StringComparison]::OrdinalIgnoreCase)) 'Reports must stay within runner temp.'
$app = Join-Path $env:LOCALAPPDATA ('Programs\EZ Nest Tester\' + $BuildId)
$trial = Join-Path $env:LOCALAPPDATA 'eznest-shop-trial'
$desktopLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'EZ Nest Tester.lnk'
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'EZ Nest Tester'
$shopApp = Join-Path $env:ProgramFiles 'eznest'
$shopData = Join-Path $env:ProgramData 'eznest'
foreach ($path in @($app,$trial,$desktopLink,$programs,$shopApp,$shopData)) {
    Assert (-not (Test-Path -LiteralPath $path)) ('Runner is not clean: ' + $path)
}
Assert (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) 'Port 8765 is already in use.'
function Assert-NoShopChanges {
    Assert (-not (Test-Path -LiteralPath $shopApp)) 'Tester created a shop program folder.'
    Assert (-not (Test-Path -LiteralPath $shopData)) 'Tester created a shop data folder.'
    Assert (-not (Get-LocalUser -Name eznest-svc -ErrorAction SilentlyContinue)) 'Tester created a service account.'
    Assert (@(Get-ScheduledTask | Where-Object TaskName -Match 'ez.?nest').Count -eq 0) 'Unexpected EZ Nest startup task.'
    Assert (@(Get-Service | Where-Object { $_.Name -match 'ez.?nest' -or $_.DisplayName -match 'ez.?nest' }).Count -eq 0) 'Unexpected EZ Nest service.'
    Assert (@(Get-NetFirewallRule | Where-Object { $_.Name -match 'ez.?nest' -or $_.DisplayName -match 'ez.?nest' }).Count -eq 0) 'Unexpected EZ Nest firewall rule.'
}
Assert-NoShopChanges
$manifest = Get-Content (Join-Path $package 'BUILD.json') -Raw | ConvertFrom-Json
Assert ($manifest.buildId -eq $BuildId -and -not $manifest.automaticUpdates) 'Wrong tester package or update defaults.'
$expectedSetup = (Get-Content -LiteralPath ($setupFile + '.sha256') -Raw).Split()[0]
Assert ((Get-FileHash -LiteralPath $setupFile).Hash.ToLowerInvariant() -eq $expectedSetup) 'Installer checksum differs.'
New-Item -ItemType Directory -Path $report -Force | Out-Null
function Install-Tester([string]$LogName) {
    $log = Join-Path $report $LogName
    $installed = Start-Process -FilePath $setupFile -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/LOG="' + $log + '"') -WindowStyle Hidden -PassThru
    Assert ($installed.WaitForExit(180000)) 'Tester installation timed out.'
    Assert ($installed.ExitCode -eq 0) 'Tester installation failed; inspect the install log.'
}
Install-Tester 'fresh-install.log'
$exe = Join-Path $app 'app\eznest.exe'
Assert (Test-Path -LiteralPath $exe) 'Tester did not install to its default per-user build folder.'
$hashes = Get-Content (Join-Path $package 'FILES.sha256.json') -Raw | ConvertFrom-Json -AsHashtable
foreach ($name in $hashes.Keys) {
    $installedPath = [IO.Path]::GetFullPath((Join-Path $app $name))
    Assert ($installedPath.StartsWith($app.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) 'Package path escaped the tester folder.'
    Assert ((Get-FileHash -LiteralPath $installedPath).Hash.ToLowerInvariant() -eq $hashes[$name]) ('Installed file differs: '+$name)
}
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($desktopLink)
Assert ($shortcut.TargetPath -eq $exe -and $shortcut.Arguments -eq '--shop-test') 'Desktop shortcut points outside the isolated tester.'
Assert-NoShopChanges
$sourceRoot = Split-Path -Parent $PSScriptRoot
& python (Join-Path $PSScriptRoot 'installed_tester_smoke.py') --exe $exe --report-dir $report --build-id $BuildId
Assert ($LASTEXITCODE -eq 0) 'Installed app browser/restart acceptance failed.'
Assert (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) 'Test app did not stop cleanly.'
$saved = Join-Path $trial 'TEST Output\synthetic-kit.pdf'
$session = Join-Path $trial 'Data\session.json'
$savedHash = (Get-FileHash -LiteralPath $saved).Hash
$sessionHash = (Get-FileHash -LiteralPath $session).Hash
Install-Tester 'maintenance-install.log'
Assert ((Get-FileHash -LiteralPath $saved).Hash -eq $savedHash) 'Maintenance install changed saved print output.'
Assert ((Get-FileHash -LiteralPath $session).Hash -eq $sessionHash) 'Maintenance install changed the saved job.'
Assert-NoShopChanges
$uninstaller = Join-Path $app 'unins000.exe'
$removed = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+(Join-Path $report 'uninstall.log')+'"') -WindowStyle Hidden -PassThru
Assert ($removed.WaitForExit(120000)) 'Tester uninstall timed out.'
Assert ($removed.ExitCode -eq 0) 'Tester uninstall failed.'
Assert (-not (Test-Path -LiteralPath $exe)) 'Uninstall retained the program executable.'
Assert (-not (Test-Path -LiteralPath $desktopLink)) 'Uninstall retained the desktop shortcut.'
Assert ((Get-FileHash -LiteralPath $saved).Hash -eq $savedHash) 'Uninstall removed or changed the print file.'
Assert ((Get-FileHash -LiteralPath $session).Hash -eq $sessionHash) 'Uninstall removed or changed the saved job.'
Assert-NoShopChanges
@{passed=$true;buildId=$BuildId;installerSha256=$expectedSetup;installedFiles=$hashes.Count;
  checks=@('default per-user install','exact packaged files','isolated desktop shortcut','browser import/nest/save',
           'app restart','same-build reinstall retains data','uninstall retains data','no shop account/task/service/firewall changes');
  limitations=@('GitHub runner account; standard-user manual test still required','default browser auto-open and native Save As need manual acceptance',
                'No physical print/cut or signed upgrade/rollback acceptance')} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $report 'installer-validation.json') -Encoding utf8
# No recursive cleanup: the disposable runner is recycled after the job.
Write-Output 'Tester fresh install, browser use, restart, maintenance install and uninstall/data retention passed.'
