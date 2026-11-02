# OUTPUT account and computer setup

Full and simple modes share the same welcome, account and computer-setup flow.
First use requires signing in to OUTPUT with its existing Privy account and
redeeming the one-time computer code issued there. The account entry is
<https://output.jeezlabs.io/workspace?tools=eznest>. Opening that page does not
complete sign-in in EZNest: only successful code redemption authorizes this
computer. There is no second Privy app, account database or password in EZNest.
The local app stores the existing protected shop credential, not the user's
Privy JWT, email OTP or browser cookies. This is computer authorization through
the signed-in shop owner, not a new personal Privy session in the desktop app.

`/api/session.account.ready` is the shared entry's authority. Before first
successful authorization, product mutations return `403 sign_in_required`.
Read-only job/inventory APIs stay available for recovery under their existing
Host/PIN checks. Pairing, check-in, disconnect, PIN management, privacy revoke,
cancel, shutdown and update/repair keep their existing access checks and remain
available. A browser localStorage skip cannot authorize product mutations.
Designer PCs must still pass the shop PIN; they cannot pair for the host.

After authorization, the host completes local printer-label, units and cut-spot
setup. Existing settings and work are retained. The setup completion is saved
on the host and shared between both modes. The Account button can reopen the
connection details. A labeled source-only development opt-out remains available;
installed builds ignore it.

A valid protected credential plus its signed check-in receipt permits subsequent
local offline work without an age limit. An explicit disconnect, a known
revocation, an altered receipt or a future timestamp requires authorization
again. Offline computers cannot discover a server-side revocation until they
reconnect. No local files or inventory are deleted on disconnect or revocation.

Sharing activity and sharing capacity are separate and stay off until the host
opts in. `output_remote.READY` still defaults to false: no unfinished browser
approval or stock-upload endpoint is enabled by this change. The existing code
exchange is used instead. No production provider settings are changed.

## What OUTPUT sees

Sent when this computer connects:

- `hostLabel`: this computer's name, once, in the pairing request
- `hostRef`: this installation id, once, when it is 32 lowercase hex characters
- `appVersion`: the app version, on each later check-in
- the shop credential, as the HTTPS bearer token on check-in and, after **Enable sharing**, on activity posts
- this computer's IP address, because that is how HTTPS works

Never sent: artwork, files, filenames, customer names or contacts, job codes,
roll ids, custom material names, exact dimensions, quantities, stock contents,
or search time. The stock ledger in `materials.sqlite3` stays on the host.

Sharing capacity and availability with the OUTPUT network (matching) is a
separate checkbox. It is off by default and does not send that information.
It is not the account connection.

OUTPUT is pre-revenue. Where that product moves money, the money is Solana
devnet test tokens. Ez Nest does not send a price.

## Connection and offline status

1. Welcome → OUTPUT account sign-in → one-time computer code → local setup.
2. A successful exchange stores the protected credential and signed receipt.
3. The workspace opens only after the server confirms authorization. Sharing
   remains off; earlier activity is not uploaded by the sign-in action.
4. Later starts, including a fresh browser profile, use that protected host
   receipt. The full and simple modes do not need separate sign-ins.

The older `outputConnection` field still describes network check-in freshness:
its 14-day freshness window and 3-day banner are not the local account gate.
The common entry uses `account.ready`, so a stale connection does not prevent
local nesting. A missing check-in route is unreachable, not a revocation.
Check-in sends only `appVersion`, not the computer name or installation id again.

## Dev mode

`EZ_NEST_DEV_NO_OUTPUT=1` and `EZ_NEST_OUTPUT_GATE_OPEN=1` are honored only by a
source checkout started with `--dev`. The Account label identifies development
mode. Installed Windows/macOS builds and the container image ignore those flags
and require server-confirmed computer authorization. This opt-out is not a
production sign-in or a way to test a real Privy session.

## Endpoints

The default service origin is `https://output.jeezlabs.io`. Pairing posts to
`/api/shop/agent/pair`. Events post to `/api/shop/telemetry`.

If `EZ_NEST_OUTPUT_URL` is set, that https origin becomes the allowed OUTPUT
host and receives the shop key. Only the person who controls the process
environment can set it. Installed builds should not set it. A saved
`outputUrl` must be `https://output.jeezlabs.io` or that same environment
origin. The environment variable wins. The value must be an `https` origin
with no path, query, username, or password. Any other host is rejected.
Redirects are not followed. There is no HTTP fallback. Changing the address
does not send anything; sharing stays off until the host pairs and agrees
on screen.

On Windows the shop key is encrypted for the user that saved it
(`eznest-svc` when the shop service is running), not for every account on
the PC. Pair from the running service. The key file is not granted to the
Users group.

| Use | Default |
| --- | --- |
| Pair | `POST https://output.jeezlabs.io/api/shop/agent/pair` |
| Events | `POST https://output.jeezlabs.io/api/shop/telemetry` |

Event schema: `eznest-observation/1`.

## Pairing request

```json
{"code": "7K4NP-QRX2M", "requestId": "0c6d2b3e-1f4a-4c5d-8e90-a1b2c3d4e5f6", "hostLabel": "SHOP-PC", "hostRef": "0123456789abcdef0123456789abcdef"}
```

The pairing request sends `hostLabel` and `hostRef` to the OUTPUT server.

`hostLabel` is this computer's name. On a Windows shop host that is the
Windows computer name (`socket.gethostname()`), limited to 60 UTF-16 code units
to match OUTPUT's request validation. Non-printable characters are removed;
truncation keeps complete Unicode characters. An empty name is sent as `localhost`.

`hostRef` is the installation id (`instance_id` in the local telemetry
database). It is included only when that id is 32 lowercase hex characters.
Otherwise the field is left out.

`code` is ten letters or digits. The operator may paste it with or without
the hyphen, in any case, with surrounding spaces. Ez Nest sends the uppercase
hyphenated form. `requestId` is a new UUID for that attempt.

The first success returns `result.token`, an `osa_` shop key (43 characters
after the `osa_` prefix). The protocol treats that key as valid for 90 days.
This client stores the key and does not run its own expiry clock. The success
body also carries `result.outpostId`. It does not include a shop name. Ez Nest
writes the key to disk before it updates consent, status, or the page, and the
host shows "Connected to OUTPUT". A `shopName` is shown only when a response
actually includes one. A repeat of the same `requestId` returns `outcome`
`replay` and no key, so the id is reused only when the connection itself
fails. A new click is a new attempt.

The code and the shop key are not written to logs or API responses.

Errors use `{"error":{"version":1,"schema":null,"code":"...","field":"...","message":"..."}}`.
Ez Nest reads `error.code` and does not show OUTPUT's `message` text.

| Situation | What the host shows |
| --- | --- |
| No network, DNS, or timeout | OUTPUT could not be reached. Check this computer's internet connection and try again. |
| HTTP 503 `disabled` | OUTPUT isn't turned on yet for this shop. Ask the admin. |
| HTTP 404 `invalid_code` | That pairing code is not valid. Ask the shop owner for a new code. |
| HTTP 401 `expired` | That pairing code has expired. Ask the shop owner for a new code. |
| HTTP 409 `consumed` | That pairing code was already used. Ask the shop owner for a new code. |
| HTTP 429 `rate_limited` | OUTPUT is busy. Wait a moment and try this code again. |
| HTTP 409 `limit` | This shop already has the maximum connected computers. Ask the shop owner to remove one in OUTPUT. |
| HTTP 409 `conflict` or any other 409 | OUTPUT did not accept the pairing request. |
| HTTP 200 `replay` without a token | OUTPUT already finished this pairing attempt, but this computer did not receive the credential. Ask the shop owner for a new code. |

## What is stored

`output-credential.bin` in the host data directory (`%ProgramData%\eznest` for
an installed shop host, `.local` for a source checkout). On Windows the file
is a DPAPI blob for this machine, with an ACL for SYSTEM, Administrators, the
current user, and `eznest-svc` when that account exists. On other systems the
file mode is `0600`. The telemetry database stores only a fingerprint of the
key.

`EZ_NEST_OUTPUT_UPLOADS=1` and a valid `EZ_NEST_OUTPUT_TOKEN` still take
precedence over a paired key, and the pairing screen says so. That credential
uses the same check-in record as a paired key.
`EZ_NEST_OUTPUT_UPLOADS=0`, including `--shop-test`, turns delivery off.
Disconnect deletes the paired file and stops sharing. It does not remove a
key that is coming from launch settings.

After a successful pairing the consent screen is shown once for that key.
**Enable sharing** is still required. New activity, including measured stock
readings already recorded on the host, is what the sender can deliver. The
shop stock ledger in `materials.sqlite3` stays on the host. Exact quantities
are not uploaded.

## Known limits

- OUTPUT check-in responses are not server-signed receipts. EZNest checks a
  local MAC on its stored check-in record; that is not a server signature.
