# OUTPUT pairing

The Ez Nest API allows nesting, sending, and stock changes without an OUTPUT
connection. The browser still shows a Connect screen based on
`outputConnection` in `/api/session`. On the shop computer, paste a
one-time pairing code from <https://output.jeezlabs.io/outpost/ez-nest>.
Designer PCs cannot pair. If the host is not connected, they see "Ask the
shop computer to connect to OUTPUT."

The browser requires the account connection on page load. Sharing activity, and
sharing capacity with the OUTPUT network, are separate and stay off until
someone on the host opts in.

The public pages are <https://output.jeezlabs.io/> and the waitlist at
<https://output.jeezlabs.io/waitlist>. Pairing, disconnect, and check-in are
accepted only from `127.0.0.1` on the host.

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

## What happens

1. Until the host is paired, the page is the Connect screen. `/api/session`
   reports `outputConnection.code: connect_required`, but other API routes do
   not reject requests because of that status. Host, session, PIN, and host-only
   checks still apply.
2. The host operator pastes a pairing code. The code is not logged or shown
   again.
3. Ez Nest sends that code to the pair endpoint and receives a scoped shop key.
4. The host stores the key. The browser opens the workspace. Activity is not
   uploaded yet.
5. After **Enable sharing**, new local activity can be delivered as
   `eznest-observation/1` events. That consent is still optional.

Earlier activity is not uploaded for that consent. Exact quantities stay on
the host.

## Offline grace

`CHECK_IN_MAX_AGE_DAYS` is 14. After a successful pairing or check-in, Ez Nest
keeps the browser workspace open when OUTPUT cannot be reached. The check-in
record is bound to the shop credential. A missing or unreadable record keeps
the browser on the Connect screen until a live check-in succeeds. A check-in record written by the previous build has no
signature. If the credential is still present, the time is not ahead of this
computer, and the record is under 14 days old, the first load signs it and
the offline grace continues. Any other unsigned record keeps the browser on
the Connect screen. A time ahead of this computer is not a current check-in.
A banner appears after 3 days offline. After 14 days without a successful
check-in, the next page load shows the Connect screen until a check-in succeeds.
If OUTPUT says the credential is unpaired or revoked, the stored credential
is removed and stays revoked; the next page load shows the Connect screen.
These connection states do not block API access.

Check-in is `POST /api/shop/agent/check-in` with `{"appVersion":"..."}` only.
The computer name and installation id are not sent again. A missing route or
a network failure counts as unreachable, not as an unpaired computer. A
response that says the credential is unpaired or revoked does.

## Dev mode

`EZ_NEST_DEV_NO_OUTPUT=1` and `EZ_NEST_OUTPUT_GATE_OPEN=1` are honored only
when the process is a source checkout started in dev mode (`--dev`, which
sets `EZ_NEST_DEV=1`). The page shows `DEV MODE: not connected to OUTPUT`
while the first of those is set. Installed Windows and macOS builds, and the
container image, ignore those variables. The browser connection screen still
applies; API access does not require these variables.

Disconnect is host-only. It returns the computer to the Connect screen.

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

- OUTPUT check-in responses are not signed receipts. This build does not
  check a signed receipt.
