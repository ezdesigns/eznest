param([switch]$NoBrowser, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$expected = Get-Content -LiteralPath (Join-Path $projectRoot 'version.json') -Raw | ConvertFrom-Json
$address = 'http://127.0.0.1:' + $Port
try {
    $existing = Invoke-RestMethod "$address/api/session" -TimeoutSec 2
    if ($existing.app -eq $expected.app -and $existing.version -eq $expected.version) {
        if (-not $NoBrowser) { Start-Process $address }
        exit 0
    }
    throw ('Another application or an older eznest build is using port ' + $Port + '. Close it first.')
} catch {
    if ($_.Exception.Message -like '*using port *') { throw }
}
$pythonRuntime = Join-Path $projectRoot '.local\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonRuntime)) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    $pythonArgs = @('-3.12')
    if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue; $pythonArgs = @() }
    if (-not $pythonCommand) { throw 'For this source build, install Python 3.12 (64-bit), or use the portable Windows package.' }
    & $pythonCommand.Source @pythonArgs -c 'import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize(chr(80)) == 8'
    if ($LASTEXITCODE -ne 0) { throw 'This source launcher requires 64-bit Python 3.12.' }
    & $pythonCommand.Source @pythonArgs -m venv (Join-Path $projectRoot '.local\venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}
& $pythonRuntime -c 'import importlib.util,sys; sys.exit(not all(map(importlib.util.find_spec, sys.argv[1:])))' spyrrow shapely numpy
if ($LASTEXITCODE -ne 0) {
    & $pythonRuntime -m pip install -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the engine dependencies.' }
}
$launched = Start-Process -FilePath $pythonRuntime -ArgumentList @('"' + (Join-Path $projectRoot 'launcher.py') + '"', '--no-browser', '--port', $Port) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot '.local\server.log') -RedirectStandardError (Join-Path $projectRoot '.local\server-error.log')
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 300
    if ($launched.HasExited) { throw 'EZ Nest could not start. See .local\server-error.log.' }
    try {
        $ready = Invoke-RestMethod "$address/api/session" -TimeoutSec 1
        if ($ready.app -eq $expected.app -and $ready.version -eq $expected.version) { if (-not $NoBrowser) { Start-Process $address }; exit 0 }
    } catch {}
}
throw 'EZ Nest did not start in time. See .local\server-error.log.'
