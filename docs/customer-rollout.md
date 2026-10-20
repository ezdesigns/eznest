# Customer Windows rollout

## v1: a useful local product

One Windows PC runs Ez Nest. Customers install `eznest-setup.exe`, open the
shortcut, and choose a printer, RIP hot folder, cut spot names, and units.
EZ Designs is an optional setup preset. An account is not required.

The daily workflow stays drop, nest, review, send. A successful Send means the
frozen pack reached the configured folder. It does **not** prove the RIP accepted
the job, the printer finished, or the cutter finished.

The listener defaults to `127.0.0.1`. Only an explicit `--lan` startup opens the
shop network. The installer translates its optional LAN choice into that flag
on the limited startup task. The task uses `eznest-svc`.

Before distributing v1, record the ONYX white-gloss test on the pinned rc.4
build, complete its review, and merge v1 separately. This readiness draft must
not be merged into the candidate branch. Retarget it after v1 merges.

## Updates: current draft limitation

Downloads require a SHA-256 sidecar and are staged locally. Stable is the
default channel; test releases require an explicit choice. Public GitHub
repositories do not require a token. Updates off prevents release requests.

The ported helper tests file replacement, settings preservation, and rollback
for a writable installation. **Automatic replacement of a Program Files install
is disabled**, including from the limited boot account. The draft is not ready
to claim unattended Windows updates.

Before checking off the updater item, implement and test the privileged
installation boundary: operator elevation on the shop PC, stopping the correct
service process, installing without rerunning first-install account setup,
restarting under `eznest-svc`, confirming the expected version is serving, and
restoring the previous version and settings after a failed start. An elevated
helper must not restart the web server as administrator. Test cancellation,
interrupted installation, a disconnected share, and reboot recovery on a
disposable Windows VM.

## Later OUTPUT phase

The readiness draft now includes a local activity foundation. On confirmation,
freezing a pack records `prepared`; a successful hot-folder write records
`sent_to_folder`. Explicit Undo records `removed_from_folder`. Downloads and
failed folder writes do not count as hot-folder deliveries. Repeated sends of
the same frozen pack count once; a newly nested pack is a new observation.

The gear's Local activity section shows a rolling 24-hour summary. SQLite stores
up to 90 days of observations in the app data directory, pruning old records on
new writes. Stored fields are the opaque pack ID, event type, UTC timestamp,
piece count, width, length, material area and artwork area. No filenames,
customer details, folder paths or artwork are copied into this database.
Tracking errors do not interrupt delivery; the activity panel reports them.
There is no backfill of previous batches.

This is not yet a machine inventory, production timer, printer-status feed or
capacity estimate. Compare these demand signals against real shop production
before developing a capacity model. No event upload exists.

The OUTPUT preference defaults off and sends nothing even when selected.
It is a placeholder, not consent to a future data transfer. Before activating
any integration, show the exact data to be shared and request fresh consent.

Start with the scope in GOALS.md: machine capabilities and available capacity.
Keep a local machine inventory and let operators review availability. Show
when information was last confirmed and let them pause or disconnect sharing.
Do not infer idle capacity merely because Ez Nest has no current layout.

The agreed OUTPUT roadmap is capacity first, then job tracking. For that later phase, define separate events:
prepared, sent to RIP, accepted by RIP, printing, printed, finishing, and
completed. Distinguish operator confirmation from a verified device event.
Assign stable job and attempt identifiers so reconnecting cannot double-count.
Keep a local event queue that survives restarts, supports retries, and can
expire stale capacity. Specify retention and deletion before enabling sync.
Do not transmit artwork, filenames, customer details, or job history under
the machine-and-capacity consent.

The first customer pilot should prove install, setup, nesting, Send, restart,
update, rollback, and uninstall without requiring Python, Git, or a terminal.
