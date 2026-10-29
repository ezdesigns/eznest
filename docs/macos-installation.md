# macOS packaging: internal pilot

`build_macos.py` builds an architecture-specific `eznest.app` and ZIP with a
SHA-256 sidecar. It uses the same dependency pins, runtime, static pages, fonts,
version and license notices as the Windows app. It requires macOS and 64-bit
Python 3.12. Build separately with arm64 Python for Apple Silicon and x86_64
Python for Intel; a passing build for one architecture does not validate the other.
No minimum macOS version or native Illustrator/RIP compatibility is certified yet.

## Build in an isolated environment

Install the pinned requirements in a dedicated Python 3.12 virtual environment.
Run from the source checkout, using an **absent** output directory outside it:

```sh
python3.12 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r requirements-build.txt
.venv-macos/bin/python build_macos.py --out /absolute/path/eznest-macos-pilot
```

The build refuses unsupported interpreters, mismatched pins and existing output
directories. PyInstaller packages the app before its ad-hoc signing step; the
script then verifies that bundle and uses macOS `ditto` to preserve its symlinks
in the ZIP. `BUILD.json` records the application version, source commit, build OS,
architecture, dependencies, dirty-checkout status, a fingerprint of packaged source
inputs, and the unnotarized pilot status. A dirty build is not attributed solely
to its recorded commit. A checksum identifies
bytes, not an approved publisher. No signing keys are read and no release is sent.

The installed app ignores `EZ_NEST_DEV_NO_OUTPUT`. On first launch the shop
Mac connects to OUTPUT with a pairing code from
<https://output.jeezlabs.io/outpost/ez-nest>. A source checkout can pass
`--dev` and set `EZ_NEST_DEV_NO_OUTPUT=1` to skip that. Official builds do not.

## Isolated local test

This is an ad-hoc-signed developer pilot, **not a Developer ID signed or notarized
installer**. Do not send it to employees or disable Gatekeeper to distribute it.
On the build Mac, use synthetic files and a new dedicated test data directory:

```sh
/absolute/path/eznest-macos-pilot/dist/eznest.app/Contents/MacOS/eznest \
  --shop-test --data-dir /absolute/path/new-eznest-test-data --port 18765
```

For a repeatable bundle test with installed Chrome or Edge and Playwright:

```sh
.venv-macos/bin/python tools/smoke_macos_bundle.py \
  --bundle /absolute/path/eznest-macos-pilot/dist/eznest.app \
  --out /absolute/path/new-macos-smoke-evidence
```

This launches the packaged executable with synthetic SVG and PDF jobs, checks
import/nest/export, verifies byte-identical exports after shutdown/restart, and
records screenshots, the build manifest and an executable checksum. It stops
its processes. This covers local bundle behavior, not installation, Gatekeeper,
physical printing, or a clean second computer.

`--shop-test` preserves the existing isolated trial behavior: loopback only,
TEST Output, no reuse of another running server, and updates off. A normal app
launch opens the simple `/web` page and stores data in the current user's
`~/Library/Application Support/eznest`. An explicit `--data-dir` still takes
precedence. Data never goes inside the app bundle, including a translocated or
read-only copy. Source checkouts and Windows portable/install paths are unchanged.
Changing the macOS user changes the default data directory; this is not shared
cross-user inventory. Use the designated shop host for shared shop stock.

The macOS entry point disables the Windows release downloader and rejects its
update-helper flags. Closing the browser does not stop the background server;
stop the foreground test command with Ctrl-C before replacing a test bundle.
The app does not install a launch agent, service or login item. No automatic Mac
upgrade or rollback is implemented by this packaging work.

## Remaining release gates

- A real build and launch, import/nest/export, restart persistence, shutdown and
  standard-user install/uninstall on each supported architecture and macOS version.
- An approved Developer ID identity and signing/notarization workflow. No certificate
  purchase, key provisioning, notarization submission or publication is authorized
  by these instructions. Sign the complete bundle with hardened runtime, validate
  the needed entitlements, notarize, staple and check Gatekeeper on a clean Mac.
- A Mac-specific updater with authenticated publisher/architecture/version checks,
  idle-work admission, failure recovery and data-preserving rollback. Never feed
  a macOS ZIP or `.app` to the existing Windows update helper.
- Two signed versions tested for upgrade and deliberate failed-start rollback on
  a clean Mac, including corrupt/wrong-publisher rejection and interruption recovery.
- Windows signed installer/rollback and the separate ONYX white-gloss physical
  gate remain required. This Mac pilot does not validate or replace either.

Implementation references: [PyInstaller macOS bundles](https://pyinstaller.org/en/stable/usage.html)
and [macOS signing notes](https://pyinstaller.org/en/stable/feature-notes.html),
plus [Apple hardened runtime](https://help.apple.com/xcode/mac/current/en.lproj/devf87a2ac8f.html).
