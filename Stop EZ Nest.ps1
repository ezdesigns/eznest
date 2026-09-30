$ErrorActionPreference = 'Stop'
$address = 'http://127.0.0.1:8765'
try {
    $session = Invoke-RestMethod "$address/api/session" -TimeoutSec 3
    if ($session.app -ne 'eznest') { throw 'Port 8765 belongs to another application. Nothing was stopped.' }
    Invoke-RestMethod "$address/api/shutdown" -Method Post -ContentType 'application/json' -Headers @{'X-EZ-Token'=$session.token} -Body '{}' -TimeoutSec 5 | Out-Null
    Write-Output 'eznest stopped. Close its browser tab when finished.'
} catch {
    Write-Error ('Could not stop eznest: ' + $_.Exception.Message)
    exit 1
}
