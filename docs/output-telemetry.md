# OUTPUT sharing

The API allows nesting, stock, and export without an OUTPUT connection. The
browser still shows the Connect screen described in
[OUTPUT pairing](output-pairing.md). Activity sharing is a second step. It
stays off until the host agrees. The host exchanges a pairing code for an
`osa_` credential, stores it in `output-credential.bin` in the host data
directory, and then shows the consent screen. Launch settings still take precedence:
`EZ_NEST_OUTPUT_UPLOADS=1` with `EZ_NEST_OUTPUT_TOKEN` is used instead of the
stored credential, and `EZ_NEST_OUTPUT_UPLOADS=0` (including `--shop-test`)
disables delivery. Do not put a token in a command argument, source, committed
file, log, or screenshot. The credential is not returned to browsers.

The settings screen on the host PC shows every transmitted field, all event
types, the measurement range widths, an illustrative JSON event, stable identity
linkability, the destination, and transport metadata before consent. A checked
agreement and **Enable sharing** are required. LAN clients cannot change consent.
Configuration alone does not upload anything.

After consent, the sender records a SQLite event-sequence cutoff and sends only
new events. Earlier events are never uploaded by that consent, including any
unsent backlog after stopping and re-enabling. Credentials or consent-contract
changes invalidate consent. Stop sharing waits for a bounded in-flight request
and prevents any subsequent request; it cannot remove data already accepted.

The default receiver is `https://output.jeezlabs.io/api/shop/telemetry` with the
`eznest-observation/1` contract. `EZ_NEST_OUTPUT_URL` or `shop.json` `outputUrl`
can select another https origin; see [OUTPUT pairing](output-pairing.md).
There is no HTTP fallback and no credential-bearing redirect.
Requests run in an isolated transport process killed and joined after a ten-second total deadline; failures back off from 30 seconds to 15
minutes. Idempotent UUIDv5 request IDs survive retry/restart. Only a matching
schema/request receipt acknowledges the local event. Malformed observations are retained locally without acknowledgement and excluded from delivery; the screen reports their count. No missing or unsafe value is guessed. No network transaction
locks the inventory database or holds the main job lock.

The exact projection lives in `telemetry_output.py`: local job codes, roll IDs,
custom names, exact values, artwork and filenames are omitted. `nest.printed`
is an operator confirmation and hot-folder writes are preparation observations,
not independent physical-printing evidence or OUTPUT order transitions. Shared
stock remains on the shop host; these observations do not replace its ledger.

`--shop-test` disables outbound sharing even if upload settings are inherited.
Tests use synthetic tokens and injected transport. They do not verify a live
credential, activate a receiver, or establish public end-to-end delivery.

## Stock summary

Share stock summary with OUTPUT is a separate host setting. It stays off until
the host turns it on in Settings. Nothing is sent unless this computer is paired
and that setting is on. `--shop-test` sends nothing.

The summary uses `eznest-stock/1`. Each roll has an opaque key, an optional
plain-text name, width in inches, length left in feet, reserved length in feet,
and a low marker. Lengths are rounded to 0.1 foot and widths to 0.1 inch.
Unknown stock has an empty length and is not marked low. At most 200 rolls are
included, and the request stays within 32 KB. Reservations, job codes, cost,
supplier, profile text, file names, and customer details are omitted. A name
that looks like a path, email address, URL, or job code is sent empty. Show
roll names in OUTPUT is on unless the host turns it off; then every name is empty.

Settings shows the JSON that would be sent. Delivery is
`PUT {output base}/api/shop/agent/stock` with the stored credential, through
the same isolated transport as activity sharing: HTTPS only, no redirects, a
ten-second deadline, and backoff from 30 seconds to 15 minutes. The same
snapshot keeps the same request id. A summary is sent when the sender starts,
about 30 seconds after stock changes, and about once an hour. Turning sharing
off sends `DELETE` to that address. The credential is not written to logs.

During installation or recovery, sharing is temporarily paused. Settings shows
the pause and requires a refresh after the host restarts before changing consent.
A candidate service cannot send events or invalidate consent while its data can
still be rolled back. After update commit, a changed consent contract requires
new agreement; rolling back a never-active candidate preserves the prior consent.
An already-started request may finish before the old service stops. Stable request
IDs allow a retry to be deduplicated by OUTPUT.
