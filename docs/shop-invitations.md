# Shops and invitations — same-network pilot

Choose one always-on host PC for the shop. Its existing material database stays
the single source of stock. Designers open that host in a browser; they do not
install separate inventory servers or copy a database between PCs. Each browser
has its own revocable access, rather than a shared account password.

On first run, enter the print shop name and choose **Start nesting**. This names the shop on this host without replacing
materials, changing cut/print settings, opening a firewall, or connecting OUTPUT.
The shop name appears in the header in both workspaces. **Already have a shop on
another PC?** takes a designer to the host's network address. **Not now** allows
a local trial without creating a shop and asks again next launch.

**Explore OUTPUT** introduces the network pilot before asking for a connection.
Its public-site link does not send the local shop name, filenames, or job data.
Existing OUTPUT shops can expand **Already use OUTPUT? Connect this computer**
to use the current code exchange. No external tab opens until a link is clicked.
Local shop creation is not OUTPUT registration; sharing still needs separate
consent. OUTPUT currently describes a devnet pilot, not production fulfillment.

For a Windows shop host, explicitly select the startup and shop-network options
during host installation. On first launch it stays on loopback until a shop or
legacy PIN exists. Create the shop locally, then have the administrator restart
the host. The shop button shows the host address once LAN mode is running. A
local-only installation does not automatically convert into a service or move
its stock; migration needs a separate reviewed workflow. No port forwarding.

On the host, select the shop name → **Create invitation**. A teammate opens the
displayed address and enters their name and invitation. Codes expire in 15
minutes and work once. Access lasts up to 30 days in that browser, including
host restarts. Signing out ends it; ask the host for a new invitation to return.
**Remove access** revokes that member immediately. **Cancel unused invitations**
invalidates outstanding codes. There is a 100-member pilot cap.

Members see the same materials, reservations, and confirmed usage. Existing
transactional revision checks reject stale edits and duplicate consumption.
Creating a shop never creates a second material ledger. Members may change stock;
only the loopback host can manage people or shop/printer/folder settings. Members
have equal working rights; individual jobs and per-action user audit are not added
by this change. Coordinate **one active nesting job at a time**: the backend still
has one shared active layout. This is not concurrent production readiness.

An existing PIN installation keeps working until a shop is created. Once created,
legacy PIN sessions no longer grant access, so removing a member cannot be bypassed
with an old shared PIN. Invite teammates again. The old PIN file is not deleted.

## Security and privacy

Invitations use 80 random bits and are consumed atomically. Session tokens use
256 random bits. Only hashes are stored in `shop-members.sqlite3`; plaintext codes
and tokens do not go in URLs, browser storage, telemetry, or logs. The browser
receives an HttpOnly, SameSite=Strict cookie (Secure under HTTPS). Each address
is limited to a few join attempts. Failed attempts are also counted for the
whole shop. A valid invitation from another address is still accepted. Sessions
expire and are checked against live membership on each request. State changes
retain same-origin checks. Names are display labels, not verified identities.
Host users are administrators under the app's existing loopback trust model.

Use a trusted shop network; configure the existing HTTPS support to protect
invites and session cookies in transit. HTTP does not protect them from a network
observer. This design follows OWASP's [single-use token guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
and [session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
It is not a public Internet login service.

Future remote locations need a hosted identity/invitation service plus an
authoritative stock allocation/synchronization protocol. Stable shop/member IDs
provide an extension point; this pilot makes no cloud sync or offline-write claim.

## Validation before rollout

Automated tests cover one-use races, expiry, cancellation, revocation, logout,
hash-only storage, limits, host-only administration, origin checks, legacy-PIN
bypass prevention, two authenticated clients reading one inventory, stale stock
edits, and first-run/join screens in both workspaces. Browser tests use synthetic
data and a separate test server; simulated remote requests are not a second-PC test.
Before rollout, test host plus a real second PC, host restart, Private-profile
firewall access, HTTPS, and disconnected/reconnected stock reads. Do not deploy
this draft over a working shop installation before those checks.
