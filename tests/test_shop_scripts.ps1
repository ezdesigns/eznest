$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$sandbox = Join-Path ([IO.Path]::GetTempPath()) ('eznest-script-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sandbox | Out-Null
$global:eznestTestCalls = [Collections.Generic.List[string]]::new()
function Assert($value, $message) { if (-not $value) { throw $message } }
# These mocks prevent the actual scripts from changing any account, ACL, task,
# firewall rule, or profile on the developer's PC or CI runner.
function global:schtasks.exe { $global:eznestTestCalls.Add('task ' + ($args -join ' ')); $global:LASTEXITCODE = 0 }
function global:netsh.exe { $global:eznestTestCalls.Add('firewall ' + ($args -join ' ')); $global:LASTEXITCODE = 0 }
function global:icacls.exe { $global:eznestTestCalls.Add('acl ' + ($args -join ' ')); $global:LASTEXITCODE = 0 }
function global:Get-LocalUser { [pscustomobject]@{ SID = [pscustomobject]@{ Value = 'S-1-5-21-1234' }; Enabled = $true } }
function global:Remove-LocalUser { param($Name, $ErrorAction); $global:eznestTestCalls.Add("remove $Name"); if ($global:eznestTestFailRemove) { throw 'In use' } }
function global:Disable-LocalUser { param($Name, $ErrorAction); $global:eznestTestCalls.Add("disable $Name") }
function global:Get-CimInstance { @() }
function global:Get-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction); $null }
function global:Remove-CimInstance { throw 'Unexpected profile deletion' }
try {
    $source = Get-Content (Join-Path $root 'installer/install-shop.ps1') -Raw
    # Inject two system-boundary fakes after function definitions, leaving the
    # installer's argument parsing and orchestration unchanged.
    $fakes = @'
function Ensure-ServiceAccount([string]$Name) { $global:eznestTestCalls.Add("account $Name"); return 'TEST-ONLY-NOT-A-CREDENTIAL' }
function Grant-BatchLogon([string]$Account) { $global:eznestTestCalls.Add("batch $Account") }
'@
    $source = $source.Replace("`$ErrorActionPreference = 'Stop'", $fakes + "`n`$ErrorActionPreference = 'Stop'")
    $installer = [scriptblock]::Create($source)
    & $installer -DataDir $sandbox -App (Join-Path $sandbox 'eznest.exe') -StartAtBoot 1
    $shop = Get-Content (Join-Path $sandbox 'shop.json') -Raw | ConvertFrom-Json
    Assert (-not $shop.lan -and -not $shop.outputNetwork) 'Network defaults must be off.'
    Assert ($global:eznestTestCalls.Contains('account eznest-svc')) 'The limited service account must be used.'
    $task = $global:eznestTestCalls | Where-Object { $_ -match '/Create' }
    Assert ($task -match '/RL LIMITED' -and $task -match '/RU eznest-svc') 'Boot task must run with limited rights.'
    Assert ($task -notmatch '--lan') 'Default startup must not use LAN.'
    Assert ($global:eznestTestCalls.Contains('task /Run /TN eznest')) 'Fresh setup must start the limited task without waiting for reboot.'
    Assert (-not ($global:eznestTestCalls | Where-Object { $_ -match 'firewall.*add rule' })) 'Default install must not open firewall.'
    $before = Get-Content (Join-Path $sandbox 'shop.json') -Raw
    $global:eznestTestCalls.Clear()
    & $installer -DataDir $sandbox -App (Join-Path $sandbox 'eznest.exe') -Lan 1 -StartAtBoot 1
    Assert (($global:eznestTestCalls | Where-Object { $_ -match '/Create' }) -match '--lan') 'Explicit LAN must reach startup arguments.'
    $after = Get-Content (Join-Path $sandbox 'shop.json') -Raw | ConvertFrom-Json
    Assert ($after.lan -eq $true -and $after.outputNetwork -eq $false) 'Explicit LAN must preserve OUTPUT off.'
    $global:eznestTestCalls.Clear()
    $global:eznestTestFailRemove = $false
    & (Join-Path $root 'installer/uninstall-shop.ps1') -DataDir $sandbox
    Assert ($global:eznestTestCalls.Contains('remove eznest-svc')) 'Uninstall must remove the service account.'
    Assert (Test-Path -LiteralPath (Join-Path $sandbox 'shop.json')) 'Uninstall must preserve shop data.'
    $global:eznestTestFailRemove = $true
    & (Join-Path $root 'installer/uninstall-shop.ps1') -DataDir $sandbox
    Assert ($global:eznestTestCalls.Contains('disable eznest-svc')) 'A signed-in account must be disabled if removal fails.'
    Write-Output 'Shop script tests passed (system changes mocked).'
} finally {
    # Only this test's verified temporary directory is removed.
    $resolved = [IO.Path]::GetFullPath($sandbox)
    $temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolved.StartsWith($temp, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notlike 'eznest-script-tests-*') { throw 'Unsafe test cleanup path' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

