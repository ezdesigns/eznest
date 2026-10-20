# Build-only signing. Secrets stay in environment/memory and an ephemeral PFX.
param([Parameter(Mandatory=$true)][string]$App)
$ErrorActionPreference = 'Stop'
$pfx = Join-Path ([IO.Path]::GetTempPath()) ('eznest-sign-' + [guid]::NewGuid().ToString('n') + '.pfx')
try {
  [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERT_BASE64))
  $tool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
    Where-Object { $_.FullName -match '\\x64\\signtool.exe$' } | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
  if (-not $tool) { throw 'signtool.exe is required to sign the app.' }
  & $tool sign /fd SHA256 /f $pfx /p $env:WINDOWS_CERT_PASSWORD /tr http://timestamp.digicert.com /td SHA256 $App
  if ($LASTEXITCODE -ne 0) { throw 'App signing failed.' }
  $signature = Get-AuthenticodeSignature -LiteralPath $App
  if ($signature.Status -ne 'Valid') { throw 'The signed app did not validate.' }
  [IO.File]::WriteAllText((Join-Path (Split-Path -Parent $App) 'update-publisher.txt'), $signature.SignerCertificate.Thumbprint)
} finally { if (Test-Path -LiteralPath $pfx) { Remove-Item -LiteralPath $pfx -Force } }
