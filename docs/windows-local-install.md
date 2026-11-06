# Windows local install and retries

Fresh setup defaults to local use. Leave the optional shop-server tasks off.
The normal shortcut runs `--local-only`, resolves `%LOCALAPPDATA%\eznest-local`
as the signed-in user, binds loopback, and disables OUTPUT uploads and update
checks. It does not configure accounts, startup tasks, firewall rules, ONYX,
or the existing `%ProgramData%\eznest` folder. Connecting to OUTPUT is optional.

Local mode is remembered across installer updates. Existing successful shop-host
installs retain their mode and data. A failed setup can be retried as local use.
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

Validation: mocked shop-script regressions, launcher/auth/build unit tests, and
Inno Setup 6.7.3 compilation with a fixture payload. Before release, use a clean
Windows VM to verify local install as a standard user, shortcut reopen, manual
upgrade, uninstall preserving data, and a separate service-mode install. No real
installer or administrative acceptance test was run on the working shop PC.
