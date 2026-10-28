# OUTPUT sharing

Sharing is off by default and never required for nesting, local inventory or
export. The host can connect with a pairing code. Ez Nest exchanges that code
for an `osa_` credential, stores it in `output-credential.bin` in the host data
directory, and then shows the existing consent screen. See
[OUTPUT pairing](output-pairing.md). Launch settings still take precedence:
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

The receiver is `https://output.jeezlabs.io/api/shop/telemetry` with the
`eznest-observation/1` contract. This depends on OUTPUT PR #105 plus its Ez Nest
schema extension. The receiver flag and migration remain off/unapplied until
approved. No arbitrary URL, HTTP fallback or credential-bearing redirect exists.
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

During installation or recovery, sharing is temporarily paused. Settings shows
the pause and requires a refresh after the host restarts before changing consent.
A candidate service cannot send events or invalidate consent while its data can
still be rolled back. After update commit, a changed consent contract requires
new agreement; rolling back a never-active candidate preserves the prior consent.
An already-started request may finish before the old service stops. Stable request
IDs allow a retry to be deduplicated by OUTPUT.
