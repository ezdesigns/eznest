# EZ Nest local tracking and proposed atom contract

The local proposal below is not the OUTPUT wire payload. The implemented
consented sender and its stricter projection are documented in
[OUTPUT sharing](output-telemetry.md). That path omits job codes, roll IDs and
other local-only fields described here; it remains off without host configuration
and explicit screen consent.

This is an implemented **local backend and proposed integration contract**, not a
registered Ez Ink hub integration. The referenced EZNEST-telemetry-brief.md and
final material.allocated contract were unavailable when this was built. Have Ez
Ink reconcile and register the fields below before connecting the real hub. Do
not edit its spine, ledger.py, render.py or board to accommodate this proposal.

## What is collected automatically

| Event | Trigger | Meaning |
| --- | --- | --- |
| nest.created | Finished layout accepted by the app | A nested layout exists; not a queued print |
| nest.waste | Same accepted layout | Estimated unused printable area outside protected artwork envelopes |
| nest.committed | Reviewed pack successfully frozen on disk | Prepared for export; not printed |
| material.allocated | First commit of that layout | Planned roll length, once per nest across all orders |
| nest.exported | Successful local file save | File saved; not proof it reached a RIP |
| nest.sent_to_print | Successful write to the explicitly configured hot folder | Handed to that folder; RIP acceptance/completion unknown |
| nest.removed_from_folder | Explicit removal through the existing app operation | Folder copy removed; does not release stock or prove cancellation |

Reading a download URL or clicking Save As does not prove a successful save or
print. Browser download completion is not recorded. A cancelled Save As may leave
a committed/prepared pack and planned allocation, but never a sent/printed event.
Start over does not cancel a frozen pack that might already be in a RIP. Use an
explicit cancellation observation if it will not be used.

Additional backend-only observations:

- `nest.linked`: link verified EZ job codes and an optional known roll before commit.
- `nest.queued`: explicit queue confirmation; preparing a pack does not infer it.
- `nest.printed`: explicit operator/connector confirmation after queue or handoff.
- `nest.cancelled`: explicit confirmation that the pack will not be used; releases
  its planned allocation. Do not submit this merely because a file disappeared.
- `material.stock_recorded`: a current measured remaining-roll reading.

No printer polling, automatic completion detection, stock purchasing, customer
files, remote dashboard, remote pairing or OUTPUT transmission is added.

## Local data and stock meaning

`telemetry.sqlite3` lives in EZ Nest's existing data directory. Exact numeric
measurements stay here for local calculations. Only allowlisted values enter it:
opaque IDs, strict `EZ-[0-9]{4,12}` job codes, enum values and measurements. It never
stores customer names, artwork/part filenames, paths, geometry or preset names.
It is separate from the existing workload.sqlite3 activity totals.

Known material classes are `moto_regular`, `moto_holographic`, `moto_chrome`,
`custom`, `unknown`. `materialKey` is the first 32 hex characters of SHA-256 of the
local preset ID; a custom name is not exposed. Treat the key as instance-scoped,
not as a globally standardized SKU. `rollId` is a separately registered opaque
32-hex ID for a physical roll. The old browser material presets are not physical
roll inventory and are not silently migrated or deducted.

Without a linked stock reading, remaining stock is unknown. For a linked roll:

- `remaining_mm`: last explicitly recorded physical reading; never auto-rewritten.
- `reservedMm`: committed plans not printed or explicitly cancelled.
- `confirmedPlannedUseSinceReadingMm`: planned lengths of confirmed prints after
  the reading. This remains an estimate; leader, trailer, spoilage and outside
  jobs are unknown. A new current reading reconciles earlier confirmed prints.
- `estimatedRemainingMm`: reading minus those confirmed planned lengths, floored
  at zero. `availableToAllocateMm` additionally subtracts active reservations.
- `shortfallMm`: positive when measured/estimated stock cannot cover allocations.
  Tracking reports it but does not block print preparation.

Stock writes use expected revision plus a unique request ID. A stale write or a
request ID reused with different data fails. Retrying an identical write is safe.
Readings must describe the roll **now**, after already confirmed prints; delayed
historical readings and confirmations require a future inventory contract.
Reprints need a fresh nest ID; resaving the same frozen pack never allocates twice.
A combined layout has one allocation, not a full-roll charge for each order.

Local nests, inventory and pending events persist until a future maintenance
policy is chosen; they are not silently dropped before delivery. Acknowledged
events older than 90 days are pruned on event writes. This does not alter the
separate workload database's 90-day retention. The API returns the latest 100
nests plus totalNests; roll totals include all relevant allocations.

## Proposed shared envelope

Every atom has exactly:

- `schema`: `eznest.telemetry.proposal.v1` (pending hub registration).
- `id`: stable SHA-256 event identity; receiver must deduplicate it durably.
- `type`: one of the event names above.
- `source`: `eznest`.
- `instanceId`: installation-local opaque UUID hex, persisted with the database.
- `appVersion`: app version string.
- `occurredAt`: UTC observation time, not a claimed printer hardware timestamp.
- `nestId`: opaque nest UUID hex; null for standalone stock readings.
- `payload`: the allowlisted fields below.

Layout event payload fields:

| Field | Type / interpretation |
| --- | --- |
| jobCodes | Array of validated EZ codes; empty means unlinked, never invented |
| materialKey | Opaque preset key or null |
| materialClass | Enum described above |
| rollId | Opaque physical-roll ID or null |
| lengthMmBand | Total sheet/roll length, 250 mm bands |
| printableWidthMmBand, rollWidthMmBand | Width, 100 mm bands; roll width may be null |
| printableAreaM2Band, rollAreaM2Band | 0.25 square metre bands; roll area may be null |
| unusedPrintablePercentBand | 5 percentage-point bands; not ink coverage or money lost |
| pieceCountBand | 10-placement bands; grouped artwork is a placement |
| sheetCountBand | 5-sheet bands |
| searchSecondsBand | 15-second bands, or null when unavailable |

Bands are strings `[lower,upper)`; exact zero is `"0"`, unknown is null. No exact
quantities are exported. IDs, timestamps, version strings and booleans are not
measurements. Proposed widths must be reconciled with Ez Ink's final banding rules.

Event-specific additional fields:

- created: `evidence="validated_layout"`.
- waste: `basis="protected_artwork_envelopes"`, `estimate=true`.
- committed: `evidence="frozen_pack"`.
- allocated: `basis="planned_roll_length"`, `consumed=false`, `stockKnown`,
  `reportedRemainingMmBand`, `availableAfterAllocationMmBand` (250 mm bands or null).
- exported: `evidence="local_file_saved"`.
- sent: `evidence="configured_hot_folder_write"`.
- removed: `evidence="explicit_folder_removal"`.
- queued/printed/cancelled: `evidence="explicit_confirmation"`.
- linked: no additional fields.

Stock events contain only `jobCodes=[]`, `rollId`, `materialKey`,
`remainingMmBand` (250 mm), and `basis="reported_measurement"`.

## Local API for a future connector

All telemetry routes require a loopback client, the existing valid Host and
`X-EZ-Token` from `/api/session`. POSTs retain the existing Origin check. These
routes are not a remote login or public dashboard API. Do not forward the app
port to the internet. The separate `/api/telemetry/output` status and consent/revoke
routes manage the opt-in OUTPUT sender; see the sharing document.

- `GET /api/telemetry`: local status, exact snapshots, roll balances, warnings,
  available event types and `outputDelivery` status. `localOnly` reflects whether
  sharing is enabled. The legacy `hubConnected` value is null when enabled; use
  the last confirmed delivery timestamp rather than inferring a live connection.
- `GET /api/telemetry/events`: first 100 pending **banded proposal atoms**. Read
  does not acknowledge delivery. These local proposal atoms are not the consented
  OUTPUT projection and must not be uploaded directly.
- `POST /api/telemetry/link`: `{id, jobCodes, rollId?}`. Current finished layout,
  before commit. Roll, if given, must exist and match its material key.
- `POST /api/telemetry/status`: `{id, action, confirmed:true}` with action `queue`,
  `printed` or `cancel`. Frozen known packs only. Completed/cancelled states are
  terminal; repeated confirmation of the same state is safe.
- `POST /api/telemetry/stock`: `{rollId, materialKey, remainingMm, requestId,
  expectedRevision}`. IDs are 32 lower-case hex; first revision is zero.

Job codes can come from an exact matching production job `order` or `code`, or
the explicit link API. They are not inferred from customer text. Existing saved
filenames are unchanged. Job-code filename conventions, including how combined
orders should be named, still need the handoff contract and an operator-facing
flow; there is no automatic filename-to-order linking claim.

## Hub adapter boundary and runnable sample

`telemetry.dispatch(data_dir, emit, enabled=False, registered_schema=None)` is
deliberately unwired. Nothing invokes it on startup or from the OUTPUT switch.
For testing only, pass `enabled=True` and this proposal schema. It invokes
`emit(atom)` and acknowledges only an exact `True` return. Failures/False leave
events pending. A crash after receiver acceptance but before local acknowledgement
can retry the same ID; receiver deduplication is mandatory. Run one dispatcher
per installation; concurrent callers can deliver duplicate IDs.

The real hub's emit signature, response, registered event names, authentication,
privacy bands and consent flow still need integration. This is not an assertion
that Ez Ink accepts this proposal. Do not enable a live connection just by setting
the old OUTPUT checkbox. Before remote use, agree on pairing/revocation, historical
backfill consent, translator/validation, and an end-to-end receiver contract test.

Run `python examples/telemetry_sample.py` from a development environment. It
creates synthetic local data, calls a fake `emit()`, and prints one
`material.allocated` atom; it does not contact a service. Tests in
`tests/test_telemetry.py` cover the same adapter, privacy, repeat delivery, stock
revision conflicts, queue states, failure isolation and HTTP authentication.

Automatic observation is best-effort: a disk/database error does not invalidate
a successful nest/export. `/api/telemetry` exposes a warning. This is operational
telemetry, not an accounting ledger or proof of physical production.
