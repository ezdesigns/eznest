# macOS shared shop host: implementation draft

The shop service edition is designed for one designated Mac that owns the shared
inventory and job workspace. Other computers use that host's browser address.
Closing a browser or logging out does not deliberately stop the system service.
The Mac must remain powered on and awake; this installer does not change sleep,
firewall or network settings. LAN access requires the explicit package `--lan`
option on first installation. Updates preserve the installed choice.

This implementation has **not been installed on a clean Mac**. The current
local pilot remains ad-hoc signed. It cannot pass the service installer's
Developer ID/notarization checks. Do not install it on a shop Mac, change its
accounts, or disable Gatekeeper to test this draft.

## Runtime and permissions

The intended administrator-authorized package installs `eznest.app` in
`/Applications` and `io.jeezlabs.eznest.plist` in `/Library/LaunchDaemons`.
launchd runs the app at boot as `_eznest`, a hidden, disabled-login account with
its own primary group and no supplementary Unix groups or administrator
privileges. `InitGroups=false` prevents inheriting implicit directory-service
groups; startup separately checks the process's real/effective UID and primary
GID. It does not use Python's macOS `getgroups()` directory-access list as a
process supplementary-group check. Actual launchd credentials remain part of
the clean-Mac acceptance gate.
Shared data stays in `/Library/Application Support/eznest`, separate from the
application. The installer refuses to adopt an unrelated existing app or data
directory; migration from an individual user's pilot needs a separate reviewed
procedure. It does not merge databases.

Opening the installed app connects to the existing service. If the host is down,
it reports that condition instead of silently starting another per-user stock
database. `--shop-test` remains an explicitly isolated synthetic trial. Normal
source, Windows and per-user Mac pilot behavior are preserved.

Existing operator-provisioned OUTPUT environment values may be preserved in the
root-private launchd configuration. No credential is created, consent granted,
production migration applied, or OUTPUT gate enabled by this installer. The
telemetry sender is a separate PR and still needs combined service validation.

## Installation and recovery transaction

`macos_service_install.py` owns the transaction; `macos_service_system.py` is its
fixed-path privileged adapter. Source execution cannot instantiate that adapter.
The package executes a bundled helper with a clean environment, without relying
on a separately installed Python. It refuses a target other than the running
Mac's boot volume. A root-owned file lock serializes installers.

Before stopping anything, the helper verifies Developer ID, hardened runtime,
notarized Gatekeeper assessment, bundle identity, architecture and version. An
update must have the same Team ID and architecture, and a strictly newer version.
The helper copies the candidate into protected staging and re-verifies it there.
The stage rejects external bundle links and special files. Space checks reserve
room for staging, data snapshots and recovery overhead.

For an existing host, a root-issued ticket requests idle admission through the
local HTTP API. A running search or an undelivered ready layout blocks admission.
The same server operation lock covers imports, material changes and the update
claim. An idle timeout cancels that ticket without killing the active job.
Once admitted, a durable blocking lease is written before launchd is stopped or
any app/configuration replacement starts. This keeps admission closed even if
power is lost and launchd starts the new candidate after a reboot. New mutations
receive HTTP 503 while the installer stops launchd,
snapshots shared data and replaces the application. Data snapshots reject links,
unexpected ownership, writable sharing and hard-linked regular files.

The new daemon starts with writes still blocked. Its PID must match launchd;
its API must report the expected version, service mode and maintenance state
continuously for ten seconds. Only after a durable commit receipt does admission
open. A failed startup restores the previous app, data and launch configuration,
then checks the restored daemon before reopening writes. A committed receipt
must never roll back material changes accepted afterward.

The root-only recovery directory is
`/Library/Application Support/eznest-update-recovery`. It retains the immediately
previous app/data, or the failed candidate and its pre-admission data. The next
approved installation reuses a closed transaction's recovery directory. An
unclosed receipt blocks another installation. The `recover` helper operation
uses only that protected receipt and fixed paths. It needs an approved signed
helper and administrator execution; it is not a browser endpoint or a general
root command runner. Power-loss recovery still requires clean-Mac validation.

## Packaging preparation

`build_macos.py --service-edition --out /new/dedicated/build` creates an ad-hoc
service-edition bundle for inspection. It does not sign with a real identity or
install anything. A release engineer must separately sign the complete bundle
with Developer ID Application and hardened runtime, validate entitlements,
notarize and staple it. Signing identities and submissions need explicit approval.

Only that verified bundle can be supplied to:

```sh
python3.12 build_macos_package.py --app /path/to/signed/eznest.app \
  --team-id APPROVED10 --out /new/dedicated/package --lan
```

`APPROVED10` is a placeholder for the approved ten-character Team ID. The command
builds an **unsigned `.pkg`**, records its checksum and explicitly false package
signing/notarization status, and performs no installation. Developer ID Installer
signing and package notarization are separate, still-required release steps.
The unsigned package must not be distributed as an employee installer.

## Evidence and remaining gates

### Update checks and desktop approval

The installed, signed service edition uses the existing update preference and
stable/test channel. It checks releases at startup and every six hours. Downloads
run in a separate bounded process, so other operators can continue working. The
catalog is limited to 1 MiB, checksums to 64 KiB, and packages to 300 MB; whole
check/download deadlines are 30/180 seconds. Failed transfers do not change the
running app. Source and ad-hoc pilots remain unable to activate this path.

Only the exact `eznest-shop-{architecture}-{version}.pkg` asset is selected.
Checksum, trusted Developer ID Installer Team ID matching the installed app,
notarized Gatekeeper assessment, and package identifier/base version must pass
before staging. A changed update preference or channel prevents promotion of an
in-flight download. A prerelease tag never enters the stable channel merely
because a release's prerelease checkbox was omitted.

On the host Mac, **Open Mac installer** invokes the installed app through the
fixed `eznest-update://install` action. No path, command or URL parameters are
accepted. The logged-in desktop user retrieves a private copy through the local
session-protected endpoint and verifies its checksum, publisher, notarization
and package identity again before opening Apple's Installer. The background
service never invokes Installer or elevates itself. The user approves the
administrator prompt; the existing idle/recovery transaction handles replacement.
Cancelling or closing Installer is not reported as a successful upgrade.

The package's short version is checked before opening Installer; its bundled
helper rechecks the full app version and architecture before stopping the host.
Final release packages must be signed/notarized, named as above, and accompanied
by a SHA-256 sidecar generated **after** signing/stapling. The unsigned preparation
artifact and its checksum are not release assets.

Native protocol registration, the desktop Installer handoff and signed release
delivery still require clean-Mac acceptance. Local tests mock those OS approval
boundaries; they do not open a real installer or submit anything for notarization.

Local tests exercise real temporary app/data snapshots, upgrade refusal,
busy-job cancellation, injected stop/configuration/start/health failures,
abrupt process death after configuration on both first install and upgrade,
rollback preservation, and committed recovery without undoing new shop writes.
Real local HTTP tests cover session authentication, ticket authorization,
undelivered-work admission, cancellation and maintenance rejection. Trust-command
outputs are simulated for unit checks; those tests do not certify a signature.

No real service account, launchd job, production data, signing key, notarization
submission or system installation was changed during implementation. Still open:

- Independent security review and required current-head CI.
- Real Developer ID app and installer signatures, notarization and Gatekeeper.
- Clean arm64 and Intel Mac install, reboot, logout, multi-PC stock operations,
  signed upgrade, failed-start rollback, interruption recovery and uninstall.
- Actual signed update discovery/download, native protocol registration and
  administrator approval through Installer. The source flow is implemented;
  no unattended installation or real release activation is claimed.
- Windows signed upgrade/rollback and the real ONYX white-gloss production test.

References: [Apple launchd system jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html),
[Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
