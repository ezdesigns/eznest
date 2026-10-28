# Connect to OUTPUT

Sharing stays off until someone on the shop host connects and agrees. Nesting,
local stock, and export do not require it. LAN clients cannot pair, disconnect,
or change consent.

## Where the contract came from

`ezdesigns/output` was not readable from the Ez Nest workspace on 2026-10-28
(the GitHub API returned 404), and `POST /api/shop/agent/pair` was not in the
public OpenAPI document. A request to that URL on the same day returned HTTP
404 `api_route_not_found`, which this client reports as pairing turned off.
The client in `output_pairing.py` is isolated so it can be adjusted when
`docs/ez-nest-pairing.md` lands on that repository.

The public waitlist page is https://output.jeezlabs.io/waitlist. That is the
page served for OUTPUT's `apps/web/app/waitlist` route. `/waitlist/ez-nest`
and `/eznest` returned 404 on the same day. Learn more uses
https://output.jeezlabs.io/.

## Assumed exchange

`POST https://output.jeezlabs.io/api/shop/agent/pair`

```json
{"code": "ABCD-1234", "hostName": "SHOP-PC", "version": "1.0.0-rc.5"}
```

Success:

```json
{"credential": "osa_<43 url-safe characters>", "shopName": "EZ Designs"}
```

A `result` object with those same fields is also accepted. Extra fields are
ignored. Redirects are not followed. The code and the credential are not
written to logs or API responses.

| Situation | What the host shows |
| --- | --- |
| No network, DNS, or timeout | OUTPUT could not be reached. Check this computer's internet connection and try again. |
| HTTP 404 `api_route_not_found`, or a disabled/feature-off code | OUTPUT pairing is turned off on the server. |
| Other HTTP 400, 401, 403, 404, 409, 410, or 422 | That pairing code is not valid or has expired. Ask the shop owner for a new code. |
| HTTP 408, 429, or 5xx | OUTPUT could not complete pairing. Try again in a few minutes. |

## What is stored

`output-credential.bin` in the host data directory (`%ProgramData%\eznest` for
an installed shop host, `.local` for a source checkout). On Windows the file
is a DPAPI blob for this machine, with an ACL for SYSTEM, Administrators, the
current user, and `eznest-svc` when that account exists. On other systems the
file mode is `0600`. The telemetry database stores only a fingerprint of the
credential.

`EZ_NEST_OUTPUT_UPLOADS=1` and a valid `EZ_NEST_OUTPUT_TOKEN` still win, and
the pairing screen says so. `EZ_NEST_OUTPUT_UPLOADS=0`, including
`--shop-test`, turns delivery off. Disconnect deletes the file and stops
sharing. It does not remove a credential that is coming from launch settings.

After a successful pairing the existing consent screen is shown once for that
credential. Enable sharing is still required. New activity, including measured
stock readings already recorded on the host, is what the sender can deliver.
The shop stock ledger in `materials.sqlite3` stays on the host. Exact
quantities are not uploaded.
