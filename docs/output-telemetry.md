# OUTPUT sharing

Sharing is off by default and never required for nesting, local inventory or
export. The host operator must configure an approved OUTPUT shop-agent
credential in `EZ_NEST_OUTPUT_TOKEN` and explicitly set
`EZ_NEST_OUTPUT_UPLOADS=1` in the launch environment. The app does not mint,
rotate or save credentials. Do not put a token in a command argument, source,
committed file or screenshot. Provisioning real credentials and enabling the
receiver remain separate operator actions requiring Ezven's approval.

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
