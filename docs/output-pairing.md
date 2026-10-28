# OUTPUT pairing

Sharing is optional and off by default. Nesting, local stock, and export do
not use it. Nothing is sent until someone on the shop host pairs this computer
and then turns sharing on. Designer PCs on the shop network cannot pair,
disconnect, or change that consent. Those actions are accepted only from
`127.0.0.1` on the host.

The public pages are <https://output.jeezlabs.io/> and the waitlist at
<https://output.jeezlabs.io/waitlist>.

## What happens

1. The host operator pastes a pairing code.
2. Ez Nest sends that code to the pair endpoint and receives a scoped shop key.
3. The host stores the key, then shows the consent screen.
4. After **Enable sharing**, new local activity can be delivered as
   `eznest-observation/1` events to the event endpoint. The shop key
   authenticates those requests.

Earlier activity is not uploaded for that consent. Exact quantities stay on
the host. The stock ledger in `materials.sqlite3` is not uploaded.

## Endpoints

The pair URL and the event URL are the client constants `ENDPOINT` in
`output_pairing.py` and `telemetry_sender.py`. This build sets them to the
OUTPUT host below. There is no Settings field and no environment variable
that points either request at a different server. A different OUTPUT host is
a change to those constants (and the address shown on the consent screen)
before the app is built. Both requests are HTTPS. Redirects are not followed.

| Use | This build |
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
Windows computer name (`socket.gethostname()`), trimmed to 80 printable
characters. An empty name is sent as `localhost`.

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
precedence over a paired key, and the pairing screen says so.
`EZ_NEST_OUTPUT_UPLOADS=0`, including `--shop-test`, turns delivery off.
Disconnect deletes the paired file and stops sharing. It does not remove a
key that is coming from launch settings.

After a successful pairing the consent screen is shown once for that key.
**Enable sharing** is still required. New activity, including measured stock
readings already recorded on the host, is what the sender can deliver. The
shop stock ledger in `materials.sqlite3` stays on the host. Exact quantities
are not uploaded.
