# Separate Windows tester

Use an installer built from `installer/tester.iss`, not the shop service installer.
It installs per Windows user as **EZ Nest Tester**, with its own AppId and a
build-specific folder under LocalAppData. It adds no service account, boot task,
firewall rule or updater. The existing shop installation is outside its scope.

The app version comes from `version.json`. Trials sharing a version are identified
by `BUILD.json` (build ID, source fingerprint, executable checksum). Check the
installer checksum supplied with the tested build. No release or signing claim
is implied by a local build.

The Start menu includes **EZ Nest test guide**. The packaged `READ FIRST.txt`
starts with uploading the synthetic example, choosing material and effort,
clicking Start nesting and saving; optional copies live in Width & copies.
Illustrator preparation is optional. `CODEX TEST PROMPT.txt` is a ready-to-paste
prompt for helping a tester on their own PC, preserving local-only trial data
and keeping contributor changes on separate draft PR branches.

## Clean-PC acceptance

1. Use a separate Windows 10/11 x64-compatible PC without an existing EZ Nest
   listener. Keep production print/cut software and live hot folders out of this test.
2. Run the tester installer as the normal Windows user. Do not disable security
   controls if the unsigned build is blocked; record the exact message.
3. Open **EZ Nest Tester**. Confirm the browser opens at `http://127.0.0.1:8765/web`.
   The trial keeps updates, shop network and OUTPUT off and uses local TEST Output.
4. Import the supplied `Examples/sample-artwork.svg`. Check all four designs are
   present and the layout appears. Save with **My computer** to a new test folder.
5. Close/reopen the browser, then stop the app using its own **Stop EZ Nest Tester**
   shortcut. Relaunch and confirm the same result restores.
6. Import a COPY of a prepared shop PDF. Record expected/detected cuts, grouped
   pieces, dimensions, length, unused space and elapsed time. Inspect the saved
   artwork and bleed against the original. Never send customer artwork as feedback.
7. Use **Send feedback**. Verify the version appears, results are unchecked by
   default, and preview contains no automatic filenames or paths. Save a report
   if GitHub access is unavailable.

Record build ID, Windows version, install/start/import/save/restart outcomes and
any exact errors. A result from a developer PC is not a clean-PC result. A PDF
export is not proof of RIP color management, printed scale or cutter registration.
Keep the detailed `TEST RESULTS.txt` local; use the app's previewable feedback
report when sharing. Missing cut boundaries are not repaired automatically:
separate stickers need closed cut lines, while decoration belongs with its
intended piece. The import error identifies the page and number of unowned
artwork groups without dropping them from the print.

The Windows installer workflow has a separate **Install and exercise the separate
Windows tester** job on a fresh GitHub-hosted runner. It builds `tester.iss`, checks
the default per-user install and shortcut, then uses synthetic PDF artwork through
the browser to import, nest and save into local TEST Output. It checks feedback
defaults, browser reload, process restart, same-build reinstall, and uninstall
with retained job/output data. The `eznest-tester-and-acceptance` artifact contains
the installer/checksum, build identity, synthetic screenshots and acceptance logs.
Only passing `app-validation.json` and `installer-validation.json` prove that run
finished; an installer artifact alone does not prove acceptance.

This job uses the runner account. The normal-user install, automatic opening of
the default browser, native Windows Save As and physical print/cut checks above
remain manual. Both acceptance entry points refuse non-hosted environments.
Never bypass those guards to execute real install/uninstall checks on a design
or shop PC. A job blocked before its steps is unverified, not a passing install.

## Manual updates

Finish the current operation and stop the tester with the shortcut belonging to
the running build. Retain a dated backup of `%LOCALAPPDATA%/eznest-shop-trial`.
Install the next verified build. Its program folder is separate; local trial data
is reused. Keep the previous build as a fallback. A source push or PR does not
update testers automatically. Do not replace protected shop rc.4.

## Build

After the required Windows checks, build using the pinned build environment:

```
python build_windows.py --portable-only --out <new-build-directory>
python build_shop_trial.py --app <new-build-directory>/dist/eznest --out <new-trial-folder> --build-id <unique-build-id>
ISCC.exe /DSourceDir=<new-trial-folder> /DMyAppVersion=<version.json-version> /DBuildId=<same-build-id> /O<installer-output> installer/tester.iss
```

Verify every entry in `FILES.sha256.json`, the ZIP CRC and SHA-256, and the
installer SHA-256. Run the packaged app against isolated test data. This installer
does not use the privileged `tests/test_installed_shop.ps1`; do not bypass that
script's disposable-runner guard on a tester or design PC.
