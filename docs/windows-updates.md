# Windows updates

## Employee workflow

1. Settings shows an available version and release notes. Checks run at startup
   and every six hours, only while updates are enabled.
2. Download the update. The app verifies the release checksum before staging it.
3. On the server PC, choose **Install when finished** and approve the Windows
   administrator prompt. If the browser does not open the protocol handler, use
   **Update eznest** in the Windows Start menu. Other shop PCs cannot approve it.
4. Finish sending the current job, or explicitly choose **Start over**. The helper
   waits through nesting, imports and file delivery. Cancel waiting update is
   available before installation begins. Closing a browser does not cancel it.
5. The app restarts under `eznest-svc`. The page reconnects after detecting the
   new server process. If startup fails, the helper restores the previous app.

An unsent frozen pack blocks installation, including a failed hot-folder send.
Downloads alone are not automatically marked delivered. Waiting expires after
12 hours; a lost helper's lease expires after five minutes. Update checks can be
turned off. Changing Test/Stable channel invalidates an already queued candidate.
Test allows prereleases; Stable excludes them. No release is published by this
workflow until separately authorized.

## First rollout requirements

Use one host PC per shop and browser bookmarks on employee PCs. Enable LAN only
on the trusted shop network with the installer's explicit Shop network choice.
Update that host once; browser clients do not need separate installers. A shop
that leaves LAN off uses the host PC's local browser.

The installer CI now performs a real fresh install on a disposable GitHub-hosted
Windows runner. It checks limited-account startup, loopback binding, the employee
page, and uninstall/data retention. It never runs on the developer's or shop PC.
This reduces the need for a spare PC during development, but does not validate
Illustrator, ONYX, physical cutting, UAC interaction or signed upgrade/rollback.
Unsigned internal pilot builds use manual installation after checksum verification.
Do not disable the signed-update guard or distribute a test certificate to employees.

Existing employees need one manual installation of the build containing this
helper. It cannot add itself to an older installation remotely. Use a separate
test PC; do not replace protected rc.4 or its ONYX white-gloss test setup.

Managed updates require the default Program Files installation, default
`%ProgramData%\eznest` data directory, port 8765, and the existing enabled `eznest`
startup task running as the limited local `eznest-svc` account. The task's existing
credentials, triggers and explicit `--lan` arguments are preserved. The helper
does not create an administrator service or store an account password.

Set the existing build secrets `WINDOWS_CERT_BASE64` and `WINDOWS_CERT_PASSWORD`
to a trusted code-signing certificate. The build signs the app before packaging
and records its publisher thumbprint inside Program Files; the workflow signs the
installer with that same certificate. No signing material belongs in Git.
Unsigned builds remain installable manually but cannot use this elevated flow.
Certificate rotation requires a separately validated/manual bootstrap upgrade.

## Trust and recovery

The protocol handler accepts no URL-supplied paths or commands. It launches the
installed helper through UAC from the interactive desktop. The helper verifies
the installed app, copies the staged installer into an administrator-controlled
directory, and verifies the copy's checksum and matching valid Authenticode
publisher before stopping anything. It rejects older/equal versions, linked
paths, unexpected task arguments, SYSTEM/admin tasks and changed candidates.

Server admission is serialized through imports and hot-folder writes. Once an
idle update claim succeeds, new operations are rejected until restart. The helper
temporarily disables the task while replacing files and restarts it without
changing its identity or network arguments. Health requires repeated successful
local responses from the expected version/process running as `eznest-svc`.

Normal startup or install failures restore the protected app backup and restart
the previous version. The data directory is never replaced or cleared, so local
activity, PDFs, settings and hot-folder configuration remain in place. Future
data-schema migrations must remain backward compatible with rollback.

Power loss or termination during replacement is not yet automatic crash recovery.
An interrupted transaction retains `Program Files\eznest-update-<id>\previous`.
An administrator must inspect the task and backup, stop any failed app, restore
that app directory or reinstall the previous checked installer, then enable/start
the existing `eznest` task. Keep the data directory and hot folder intact. Do not
delete recovery directories until the running version is confirmed healthy.

## Required isolated Windows acceptance test

Automated Python/browser tests cover queueing, cancellation, expiry, channel/off
changes and operation admission. PowerShell tests exercise signature rejection,
limited-task checks, successful install coordination and rollback with all system
operations mocked. These are not evidence of a real elevated upgrade.

Before employee rollout, test two signed versions on a disposable Windows PC/VM:

- Seed settings, synthetic workload records and a test hot folder; record hashes.
- Start the old version using its limited task. Queue an update during nesting;
  verify it waits through preview and delivery. Try a second browser operation.
- Cancel UAC and cancel a queued update; confirm the old app continues working.
- Complete an update; verify version, service identity, loopback/LAN behavior,
  unchanged settings/tracking, unchanged test-folder contents and browser recovery.
- Use a controlled signed build that fails health; verify the previous app is
  restored and the same limited task starts it. Confirm settings and tracking.
- Reject corrupt, unsigned, other-publisher and older installers before shutdown.
- Test updates off, Test/Stable selection, network failure and low disk space.
- Reboot after success and rollback. Check the retained task, installer/uninstall
  registration and the separate interruption-recovery procedure.

Record actual versions, signatures, account identity and results in the draft PR.
Keep the readiness checklist's real install/rollback item open until this passes.

