# Connect to OUTPUT

Sharing stays off until someone on the shop host connects and agrees. Nesting,
local stock, and export do not require it. LAN clients cannot pair, disconnect,
or change consent.

## Where the contract came from

The pairing contract is `docs/ez-nest-pairing.md` on `main` in
`ezdesigns/output` (PRs #110 and #113). This workspace's GitHub token received
HTTP 404 for that repository, so the client follows the merged contract as
specified with those PRs. The telemetry projection stays
`eznest-observation/1`.

The public waitlist page is https://output.jeezlabs.io/waitlist. Learn more
uses https://output.jeezlabs.io/.

## Exchange

`POST https://output.jeezlabs.io/api/shop/agent/pair`

```json
{"code": "7K4NP-QRX2M", "requestId": "0c6d2b3e-1f4a-4c5d-8e90-a1b2c3d4e5f6", "hostLabel": "SHOP-PC", "hostRef": "0123456789abcdef0123456789abcdef"}
```

`code` is ten letters or digits. Staff may paste it with or without the
hyphen, in any case, with surrounding spaces. Ez Nest sends the uppercase
hyphenated form. `requestId` is a new UUID for that attempt. `hostLabel` is
this computer's name. `hostRef` is the local installation id when it is 32
lowercase hex characters; it is left out otherwise.

The first success returns `result.token`, an `osa_` credential that OUTPUT
keeps for 90 days. Ez Nest writes that credential to disk before it updates
consent, status, or the page. A repeat of the same `requestId` returns
`outcome` `replay` and no token, so the id is reused only when the connection
itself fails. A new click is a new attempt.

Redirects are not followed. The code and the credential are not written to
logs or API responses. A shop name in `result.shopName` is shown when OUTPUT
sends one. The page says OUTPUT when it does not.

| Situation | What the host shows |
| --- | --- |
| No network, DNS, or timeout | OUTPUT could not be reached. Check this computer's internet connection and try again. |
| HTTP 503 `disabled` | OUTPUT isn't turned on yet for this shop. Ask the admin. |
| HTTP 404 `invalid_code` | That pairing code is not valid. Ask the shop owner for a new code. |
| HTTP 401 `expired` | That pairing code has expired. Ask the shop owner for a new code. |
| HTTP 409 `consumed` | That pairing code was already used. Ask the shop owner for a new code. |
| HTTP 429 `rate_limited` | OUTPUT is busy. Wait a moment and try this code again. |
| HTTP 409 `limit` | This shop already has as many Ez Nest connections as OUTPUT allows. Ask the admin. |
| HTTP 200 `replay` without a token | OUTPUT already finished this pairing attempt, but this computer did not receive the credential. Ask the shop owner for a new code. |

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
