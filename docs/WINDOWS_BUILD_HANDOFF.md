# Windows build handoff

This is the procedure for an AI coding agent on an office Windows PC. GitHub
Actions is blocked by billing, so this build is manual. The installer may be
unsigned. Windows SmartScreen is expected to warn. Do not remove the signing
or update logic in `build_windows.py`, `installer/sign-payload.ps1`, or
`installer/update-shop.ps1`.

Do not bump `version.json`. Do not push a `v*` tag. Do not point this work at
draft PR #6. Do not use the live ONYX hot folder. Do not print a pairing code,
an `osa_` credential, or a screenshot that shows either one.

The Linux workspace that wrote this file did not build `eznest-setup.exe` and
did not install it on Windows. Record every command and result in the log at
the end.

## 1. Prerequisites

Open PowerShell 7 in the Ez Nest checkout. The branch to build is the PR
branch that contains this file, not an unrelated draft.

```powershell
py -3.12 -c "import struct,sys; print(sys.version); print(struct.calcsize('P')*8)"
node --version
git status -sb
git rev-parse HEAD
(Get-Content version.json -Raw | ConvertFrom-Json).version
```

Expected:

- Python `3.12.x` and `64`. Stop if it is 32-bit or another Python.
- Node is only for `node --check`. Node 22 or 24 is enough. There is no npm install.
- `version.json` is `1.0.0-rc.5` unless the owner changed it on purpose.
- The checkout is the pairing branch and `git status` has no surprise edits.

Create a virtual environment outside any path that contains a space. `C:\eznest-build` is the build output, not the venv.

```powershell
py -3.12 -m venv .local\venv
.\.local\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.\.local\venv\Scripts\python.exe -m pip install playwright
```

Expected: pip finishes with the pins in those two files. `pyinstaller` is `6.22.3` and `pyinstaller-hooks-contrib` is `2026.7`. If pip wants to change a pin, stop. Do not loosen versions.

Inno Setup must be 6.3 or newer because `installer/eznest.iss` calls `ExecAndLogOutput`. The GitHub workflow uses 6.7.3. An older `ISCC.exe` on `PATH` is ignored when 6.3 or newer is installed. If only an older compiler is present, the build stops with that reason.

```powershell
$installer = "$env:TEMP\innosetup-6.7.3.exe"
Invoke-WebRequest -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe" -OutFile $installer
Start-Process -FilePath $installer -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-" -Wait
Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
```

Expected: the last command prints `True`.

Leave `WINDOWS_CERT_BASE64` and `WINDOWS_CERT_PASSWORD` unset for this unsigned office build. Do not delete the signing script.

## 2. Build the installer

```powershell
.\.local\venv\Scripts\python.exe -m unittest discover -s tests -p "test_output_*.py"
.\.local\venv\Scripts\python.exe -m unittest tests.test_telemetry_sender tests.test_telemetry_consent tests.test_shop_deploy tests.test_windows_build
node --check web.js
.\.local\venv\Scripts\python.exe build_windows.py --out C:\eznest-build
```

Expected:

- The unit tests pass.
- The build prints `Portable app: C:\eznest-build\dist\eznest`.
- It prints `Inno Setup:` and a version of 6.3 or newer.
- It prints `Installer: <repo>\installer\Output\eznest-setup.exe`, a commit, and a sha256.
- `installer\Output\eznest-setup.exe` exists.
- `installer\Output\BUILD.json` has the same sha256 as `Get-FileHash installer\Output\eznest-setup.exe -Algorithm SHA256`.

If the build directory already contains `dist\eznest`, choose a new directory. Do not reuse `C:\eznest-build` after a failed partial build without deleting it. A path with a space is rejected on purpose.

If Inno Setup is missing, the portable folder is still produced and the installer step returns without an exe. That is not a finished installer. Install 6.7.3 and run the same command again with a new `--out` directory.

Write the checksum file next to the exe:

```powershell
$setup = "installer\Output\eznest-setup.exe"
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  eznest-setup.exe" | Set-Content -LiteralPath "$setup.sha256" -Encoding ascii
Get-Content "installer\Output\BUILD.json"
Get-Content "$setup.sha256"
```

Expected: the hash in `BUILD.json`, the `.sha256` file, and `Get-FileHash` all match.

## 3. Smoke-test the portable app

Use a second data directory so this does not touch an installed shop.

```powershell
$env:EZ_NEST_OUTPUT_UPLOADS = $null
$env:EZ_NEST_OUTPUT_TOKEN = $null
C:\eznest-build\dist\eznest\eznest.exe --web --no-browser --data-dir C:\eznest-smoke
```

Expected: a console or log line `eznest ready: http://127.0.0.1:8765/web`. Open that URL in Edge or Chrome.

- The page loads. In-house is selected.
- Don't print is light green and shows the Still get paid badge.
- The dialog title is exactly `Don't print it. Let another shop do it.`
- Join the waitlist opens https://output.jeezlabs.io/waitlist in a new tab.
- Learn more opens https://output.jeezlabs.io/ in a new tab.
- Settings, Share activity with OUTPUT, shows Connect to OUTPUT.
- A nonsense code such as `NOPE-0000` shows a clear failure (bad code, server feature off, or offline). It must not show an `osa_` string.
- Close the window. Run `C:\eznest-build\dist\eznest\Stop EZ Nest.cmd` if port 8765 stays busy.

## 4. Install on a clean PC

Copy `eznest-setup.exe` and `eznest-setup.exe.sha256` to the clean PC. Compare the hash before running it.

SmartScreen: **More info**, then **Run anyway**. That warning is expected for an unsigned file. Do not disable SmartScreen for the whole PC.

Run `eznest-setup.exe /LOG=C:\eznest-setup.log`.

In the wizard:

- Leave **Start eznest when Windows starts** checked.
- Check **Shop network** only on the PC that will be the shop host.
- Leave **Disable updates** unchecked unless this PC must not call GitHub.
- Check **This PC runs ONYX** only when the hot folder is on this PC.

Expected:

- Installs to `C:\Program Files\eznest`.
- Creates local user `eznest-svc`. That user is not an administrator.
- Scheduled task `\eznest` runs as `eznest-svc` with Run level Limited, at startup, with `--web --no-browser --data-dir "C:\ProgramData\eznest"`.
- With Shop network checked, the task argument includes `--lan`, and a private-profile firewall rule named `eznest` allows TCP 8765.
- `http://127.0.0.1:8765/web` opens on the host.
- If shop setup fails, the wizard says setup did not finish. Read `C:\eznest-setup.log`. A retry is safe: the service account is not left in Administrators, and a second run does not require the Administrators membership list to be fully resolvable.
- If the task is registered but does not start, sign out and back in, or restart, then run the installer again. The log should name batch logon rather than a blank failure.

Do not install over the protected shop-test copy of rc.4. Use a PC or VM that does not already run that installation.

## 5. Shop host and a second PC

On the host, Settings shows the shop-network address when Shop network was installed. On the second PC, open `http://<host-name>:8765/web` in a browser. Do not use `127.0.0.1` on the second PC. Do not use guest Wi-Fi.

Expected:

- The client page loads and can prepare a job.
- Settings on the client can be viewed, but Connect to OUTPUT and Enable sharing report that sharing is managed on the host computer.
- The client never receives a credential. The host's Connect status shows a shop name, not an `osa_` value.

## 6. Shared stock

On the host:

1. Open **Material & stock**.
2. Save a material with a measured **Length left on roll**. Use a synthetic name such as `Office test roll`.
3. On the client, refresh the page. The same material and length appear.
4. Nest a small synthetic file on the client. Nesting does not reduce the length.
5. **Reserve for this job** on the client. The host shows the same reservation.
6. On the host, **Confirm material used** once. The length decreases by the reserved amount.
7. Choose **Confirm material used** again. The length does not decrease a second time.
8. **Release reservation** on a different reserved job returns that reservation and does not restore material that was already confirmed.

Expected: both PCs show one shared ledger. No customer name or artwork filename is required for the stock row.

## 7. Connect to OUTPUT and the popup

On the host only, Settings → **Share activity with OUTPUT**:

1. Paste the single-use code the shop owner generated in OUTPUT. Choose **Connect**.
2. Expected success: `Connected to <shop name>.` Then the sharing details are on screen. Check the agreement and choose **Enable sharing**.
3. Expected failures, in the host's own words:
   - Offline: `OUTPUT could not be reached. Check this computer's internet connection and try again.`
   - Bad or expired code: `That pairing code is not valid or has expired. Ask the shop owner for a new code.`
   - Feature disabled: `OUTPUT pairing is turned off on the server.`
4. The page must not display the credential. `%ProgramData%\eznest\output-credential.bin` exists after success and is not a text file containing `osa_`.
5. If `EZ_NEST_OUTPUT_UPLOADS=1` and `EZ_NEST_OUTPUT_TOKEN` are set on the host, the screen says launch settings are in use and does not spend the pairing code. Remove those variables and restart the host before pairing.
6. **Disconnect** removes the saved credential and stops sharing. Pairing is required again.
7. Open **Don't print**. Confirm the title, the three "Use it when" lines, the light-green button, the green Still get paid badge, black Join the waitlist and Learn more actions, and that the copy does not mention fees or how a shop is chosen.

If OUTPUT has not published pairing yet, a clear disabled or offline error is the expected result. On 2026-10-28 the public pair URL returned HTTP 404 `api_route_not_found`, and Ez Nest showed `OUTPUT pairing is turned off on the server.` Record the exact sentence you see. Do not invent a token to make the success path look done.

## 8. Share the installer

Prefer a file copy or a private draft release. Do not create a tag that starts with `v`. The Windows workflow publishes on `v*` tags when Actions is running.

Draft release, from the checkout, after `gh auth login` as someone who can create releases:

```powershell
gh release create office-1.0.0-rc.5-YYYYMMDD --draft --target <commit> --title "Ez Nest office build 1.0.0-rc.5" --notes "Unsigned office build. SmartScreen warning expected. Not a published release." "installer\Output\eznest-setup.exe" "installer\Output\eznest-setup.exe.sha256" "installer\Output\BUILD.json"
```

Expected: a draft release. It is not the public shop release. Do not mark it latest. Do not attach it to a `v*` tag.

Alternatively copy the exe, the `.sha256` file, and `BUILD.json` to the office share used for this demo. Do not email the credential and do not put the pairing code in the release notes.

## Checklist

| Check | Expected | Result |
| --- | --- | --- |
| Python 3.12, 64-bit | version line and `64` | |
| Pins installed | requirements and requirements-build, no substitutions | |
| Inno Setup | 6.7.3, or another 6.3+ chosen over an older PATH copy | |
| `eznest-setup.exe` | file exists | |
| SHA-256 | BUILD.json, `.sha256`, and Get-FileHash match | |
| Portable smoke | page opens on 127.0.0.1 | |
| Popup title | `Don't print it. Let another shop do it.` | |
| Waitlist link | https://output.jeezlabs.io/waitlist | |
| Learn more link | https://output.jeezlabs.io/ | |
| Clean install | Program Files, eznest-svc, limited startup task | |
| Shop network | second PC opens the host URL | |
| Shared stock | client sees the host roll; confirm deducts once | |
| Connect success or clear failure | shop name, or offline / bad code / feature disabled | |
| Credential not shown | no `osa_` on screen or in the log | |
| Disconnect | pairing file gone, sharing off | |
| SmartScreen | warning seen, Run anyway, signing logic still present | |
| Release | draft or file copy, no `v*` tag | |

## Log

```text
Date:
PC:
Windows version:
Git commit:
Python:
Inno Setup:
Installer sha256:
Smoke URL:
Clean install log: C:\eznest-setup.log
Task account and run level:
Second PC URL:
Stock before / after confirm:
OUTPUT connect result (sentence only, no code or credential):
Popup title seen:
Links opened:
What was not verified:
```
