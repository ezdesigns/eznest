# Set up the Illustrator pilot on the separate design PC

This is the handoff for Codex and the employee testing a real motocross kit.
It sets up a local test on the **Windows PC with Illustrator**, separate from
the shop PC running ONYX and the protected rc.4 installation. It does not
authorize printing, cutting, replacing the shop installation, or publishing.

## Paste this into Codex on the design PC

> Set up ezdesigns/eznest for an Illustrator pilot on this separate Windows design
> PC. Read GOALS.md, AGENTS.md, CONTRIBUTING.md and START-CODEX.md. Use the latest
> open readiness draft PR #4 branch, cursor/shop-open-handoff-9891; verify the
> branch and preserve local changes. Follow START-CODEX.md through setup and a
> real motocross-file test. Prefer the isolated source launch described there.
> Create local test folders, prepare the runtime, start the app, configure its
> test output, and help me run Nest in eznest. Do the routine setup yourself;
> ask me only for missing shop settings, my test file, required OS permissions,
> or steps that need my eyes or Illustrator interaction you cannot perform.
> Keep artwork local and use a copy. Keep 127.0.0.1, updates off and OUTPUT off.
> Do not change the shop PC, PR #1, rc.4, accounts, tasks, firewall rules or live
> hot folders. Do not merge or release. Leave a local test report and exact
> restart instructions, with unfinished checks clearly marked.

## 1. Verify the machine and checkout

Codex should read the repository instructions first and inspect the current
checkout before changing anything. Fetch the current PR metadata when available;
verify it is still draft and targets PR #1's branch. Do not blindly reset or
switch a dirty checkout. Protect PR #1 / rc.4 at
`2c1f547a2449f600711ccb21ddf235f9b9114f00`. If the branch policy has changed,
resolve that before changing repository state.

Confirm this is the separate design PC, Illustrator is installed, and it is
not the host used for the protected shop test. Do not remotely administer the
shop PC. Inspect this machine for an existing eznest installation, boot task,
running process and listener on TCP 8765. Useful read-only checks:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue
Get-Process eznest -ErrorAction SilentlyContinue
Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object TaskName -Like '*eznest*'
Test-Path (Join-Path $env:ProgramFiles 'eznest')
Test-Path (Join-Path $env:ProgramData 'eznest')
py -3.12 --version
```

If the port is occupied, identify the process and intended use. Do not kill it,
change its settings or silently attach this test to it. The launcher can reuse
an existing same-version server even when a different data directory was passed;
the version alone does not prove isolation. This bridge currently requires port
8765 on the same PC as Illustrator. A different port or remote host is not a
supported workaround for the script.

Collect only these missing production details, together where possible:

- The local path to one motocross AI file and any linked assets it needs.
- The exact existing Adobe PDF preset normally used for ONYX.
- The actual printable width in inches and existing bleed in millimetres.

Regular is the only configured material. Do not invent Chrome/Holographic rules,
color substitutions, bleed, or a PDF preset. A preset absent from this Illustrator
installation needs the operator's approved preset before production comparison.

## 2. Make a local test workspace

Use a new, uniquely named folder under the user's local app-data directory,
outside the repository and outside cloud-synced Documents/Desktop folders.
Do not use a network share or any ONYX-watched directory. Example, in PowerShell:

```powershell
$pilotRoot = Join-Path $env:LOCALAPPDATA ('eznest-pilot-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $pilotRoot) { throw 'Choose a new pilot folder.' }
New-Item -ItemType Directory -Path $pilotRoot | Out-Null
foreach ($name in @('Artwork','Output','Data','Reports')) {
    New-Item -ItemType Directory -Path (Join-Path $pilotRoot $name) | Out-Null
}
```

Confirm Output is not watched by a RIP. Copy the chosen artwork and required
linked assets to Artwork; never move or overwrite the originals. Record a hash
of the original AI file locally before testing and compare it afterwards.
Never commit these files, their names/paths, screenshots of customer art, logs
containing private details, or the Data folder. Do not upload artwork to OUTPUT,
GitHub, cloud drives or chat. Inspect it locally in Illustrator.

## 3. Start the draft without installing a shop service

For this first design-PC test, use the source checkout and its isolated Python
environment. This avoids the installer, startup task, account changes and UAC.
The Windows service account policy remains `eznest-svc`; this temporary source
process runs as the signed-in employee and does not create a replacement service.

From the verified repository root, use 64-bit Python 3.12:

```powershell
py -3.12 -m venv .local/pilot-venv
& ./.local/pilot-venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$env:EZ_NEST_UPDATES = '0'
& ./.local/pilot-venv/Scripts/python.exe launcher.py --web --data-dir (Join-Path $pilotRoot 'Data')
```

Do not overwrite an existing environment without inspecting it. If Python is
missing, use the available approved installation mechanism and handle any actual
permission prompt; do not change global execution policies or disable security
software. No Node, compiler, or full automated suite is needed just to run this
pilot. A terminal running the server stays open; use a second terminal for
inspection. If a background launch is needed, keep its window hidden and record
the exact process ID, executable, arguments and data directory.

Open `http://127.0.0.1:8765/web`. Verify the listener belongs to this pilot process
and binds only to 127.0.0.1. Verify state is written under the chosen Data folder.
Do not start with `--lan`. Do not run installer/uninstaller helpers or
`tests/test_installed_shop.ps1` on this PC.

If a packaged install is specifically preferred later, use a successful draft
CI artifact and verify its commit in BUILD.json and executable SHA-256 against
the supplied metadata. A version string is insufficient because draft commits
share a version. Do not use an old artifact just because its URL still works.
The installer changes machine state and is not the default route in this guide.
Unsigned builds are not signed production releases; do not bypass Windows
security policy or weaken the signed-update checks.

## 4. Configure the app and Illustrator

Complete first-run app setup using the new Output folder, printer label
`Illustrator pilot - NO PRINT`, inches, and cut spots `CutContour_Thru-cut` and
`CutContour_Kiss-cut`. Do not apply a preset that supplies a live shop path.
Leave "This PC runs ONYX" off, shop network off, updates off, and OUTPUT off.
Verify the saved destination is exactly the new Output folder before any send.

Use the scripts from this same checkout's `illustrator/` folder. Keep these
four files together:

- `Nest in eznest.jsx`
- `Prepare for EZ Nest.jsx`
- `EZ Nest Settings.jsx`
- `bridge-core.js`

For the pilot, run **File > Scripts > Other Script** in Illustrator and choose
`Nest in eznest.jsx`. No changes to Illustrator's installed Scripts folder are
needed. After the pilot works, the operator can use the permanent menu setup in
[the script guide](illustrator/START%20HERE.txt).

On the first run choose the approved PDF preset, Regular, printable width and
existing bleed. Settings are remembered per Windows user. `EZ Nest Settings.jsx`
edits them later, even with no artwork open. If a saved PDF preset is missing,
setup reopens; do not substitute another preset merely to finish the test.

Codex should perform available file/runtime/browser operations directly. If its
tools cannot operate Illustrator, give the operator the exact next menu action
and wait for the result. Do not claim a JSX syntax test or simulated Illustrator
host is a real Illustrator test. The user handles OS consent and Adobe sign-in.

## 5. Walk one real motocross kit through

1. Open the copied AI file in Illustrator. Resolve missing fonts/links using the
   operator's normal workflow. Finish colors and existing bleed, then save the
   copy. Keep the normal source file unchanged.
2. Check `print`, `thru-cut`, and `kiss cut` layers. Select complete artwork and
   cut paths together, initially one manageable kit or subset. Cut paths must be
   separate unfilled strokes, not filled objects or clipping masks. Select no
   more than 100 top-level objects; do not select parents and children together.
3. Run **Nest in eznest**. It creates a separate production document, exports the
   chosen PDF preset, returns focus to the source document and opens the browser.
   The script does not generate bleed, fix clipping groups or recolor artwork.
4. Finish app setup if prompted. An empty workspace loads automatically. If a
   job is already open, preserve it until the operator finishes or explicitly
   discards it. Do not automatically approve replacement dialogs.
5. Start with **1 set**. Review every piece, expected piece count, dimensions,
   colors, both cut types, spacing, printable width and missing/clipped artwork.
   A green cut check alone does not prove production correctness.
6. Confirm the destination is the isolated Output folder. Choose **Review and
   send** after the operator accepts the preview. Verify files appear there.
   This is a test-folder delivery, not a printed job or an ONYX connection.
7. Open the resulting `artwork.pdf` in Illustrator. Compare it with the normal
   production PDF: actual size of known parts, artwork, spots, layer names,
   transparency and bleed. Record mismatches; do not guess tolerances or fix
   source artwork silently. The operator must accept the comparison.
8. Refresh the browser and confirm the sent result is retained. Use **Next job**,
   select the saved source copy again, and run the script again. Verify the PDF
   preset/material dialog is skipped. Change sets to **2**, verify the expected
   piece quantity doubles, and review again before any second test send.
9. Inspect local activity: successful test sends appear locally. Re-sending one
   frozen pack should not double-count it; a fresh Illustrator export is a new
   attempt. These observations do not indicate printing or available capacity.

Do not move these files to a live ONYX hot folder. A physical print/cut check is
a separate operator-controlled stage. This design-PC test does not satisfy the
protected rc.4 ONYX white-gloss gate or authorize a merge/release.

## 6. Leave the employee ready to repeat it

Write `Reports/pilot-result.txt` outside the repo with:

- Date, repository commit, Windows/Illustrator versions and launch method.
- Test folder, data folder, listener/process identity and exact restart command.
- PDF preset, Regular material, width, bleed and tested set counts.
- Pass/fail/not-tested for export, automatic load, dimensions, artwork, cut paths,
  test delivery, remembered settings, refresh and local activity.
- Original-file hash comparison, operator observations and unresolved problems.
- Explicit "ONYX print/cut not tested" unless a separately authorized physical
  test actually happened. No production-ready claim from automated tests alone.

Provide an easy local restart shortcut/script using the verified absolute Python
and checkout paths, `--web`, the same explicit Data folder and updates disabled.
It must check for an occupied port before starting, identify an existing pilot
before reusing it, and never stop unrelated processes. Keep the shortcut outside
the repository. No auto-start task or firewall rule is needed for this test.

Finish with the simple operator flow: **prepare/save/select in Illustrator →
Nest in eznest → sets → review → send to TEST Output**. Explain where the output
and report are. Stop only the identified pilot process when the operator is
finished; preserve test files and data for review. Do not run a broad stop helper,
uninstall an existing app, or recursively delete the test workspace automatically.

If something fails, keep the original and exported copy, record the exact error
locally, and isolate a synthetic reproduction before committing a fix. Repository
fixes stay on the readiness draft with appropriate tests and no customer files.
