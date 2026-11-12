# Windows local install and retries

Fresh setup defaults to local use. Leave the optional shop-server tasks off.
**Start Ez Nest when I sign in to Windows** is selected by default. It starts
quietly after Windows sign-in; it does not open a browser. Clear that checkbox
if automatic startup is not wanted. Windows Settings > Apps > Startup can also
disable it later. This is sign-in startup, not a service that runs before login.

The normal shortcut runs `--local-only`, resolves `%LOCALAPPDATA%\eznest-local`
as the signed-in user, binds loopback, and disables OUTPUT uploads and update
checks. It does not configure service accounts, scheduled tasks, firewall rules, ONYX,
or the existing `%ProgramData%\eznest` folder. Connecting to OUTPUT is optional.

Local mode is remembered across installer updates. Existing successful shop-host
installs retain their mode and data. A failed setup can be retried as local use.
Updates preserve the existing sign-in startup choice (including older installations
without it) instead of applying fresh-install defaults. Shared hosts keep their
existing boot task and do not get a second sign-in launcher. The sign-in shortcut
is installed in Common Startup so it runs as the signed-in user, even when someone
else supplied administrator permission for setup. Each Windows account in local
mode keeps its own local data. Designers sharing a shop use that host's browser link.

Shop identity, member sessions, material stock/reservations and private saved jobs
live outside the application directory. Updating replaces the application, not
those records. Returning designers use the same shop address and browser; clearing
browser data, using private browsing, expired sessions or revoked membership can
still require restoring access. Uninstall removes automatic startup, but retains data.
Opening the shortcut again reuses only the same version and local data identity;
another listener is reported instead of opening the wrong inventory. Updates for
local mode are installed manually with the normal installer.

Shop-host setup remains an explicit selection. Its hidden helper is noninteractive
and never waits for an HTTPS prompt. It preserves the app-managed ACL and contents
of `output-credential.bin` and its temporary file; it does not take ownership or
attempt to migrate another Windows identity's DPAPI credential. Other ACL errors
still stop setup. Changing the service identity may require reconnecting OUTPUT
later; installation does not pair automatically.

An access-denied/code 5 error replacing the executable can still mean a running
process or Windows permissions. Close Ez Nest normally and retry. Do not disable
security software, change execution policy, delete shop data, or forcibly end RIP
processes. This change does not claim to solve all Windows code 5 errors.

Validation: the Windows installer workflow runs local and service acceptance on
separate disposable Windows runners. It tests default sign-in startup, duplicate
launch, maintenance install, startup opt-out, and uninstall. Both modes seed a
synthetic shop, stock/reservations, saved upload and browser membership, then verify
them after update and uninstall. The packaged app must accept the original member
cookie after restart. Portable update/failed-update rollback tests use the same
fixture. No real installer or administrative acceptance test runs on the working
shop PC. CI launches the startup shortcut's target; an actual Windows sign-out/in
and an over-the-shoulder standard-user elevation remain manual acceptance checks.
