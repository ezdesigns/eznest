# Goals

Ez Nest is a free, open-source, self-updating desktop nesting tool that any print shop can install in minutes. It nests files, adds cut marks, and sends them to the RIP hot folder. It is built first for EZ Designs (Austin). Later, and only if a shop opts in, it is how shops join the OUTPUT print production network.

## Who it is for

A print shop that already has a RIP and a hot folder. The operator drops the day's files, nests them, and sends the sheet. No account is required to do that.

EZ Designs in Austin is the first shop. Its printer, cut spot names, units, and hot folder are a preset a shop can apply on first run. They are not required.

Other shops use the same install. They type their own hot folder, printer, cut names, and units.

## What v1 must do

- Install on one Windows PC in minutes. The other shop computers only open a browser.
- Run on that PC. The page is `http://127.0.0.1:8765/web` unless the shop turns the shop network on.
- Nest PDF, PDF-compatible AI, and SVG. Add cut marks. Send one frozen pack to the RIP hot folder.
- Ask once, the first time it opens, for the hot folder, the printer, the cut spot names, and the units.
- Show a clear error on Send when that hot folder or share is missing or cannot be reached.
- Update from a checked installer. If the new build does not start, put the previous build back. Shop settings and the hot folder stay.
- Let a shop report a problem. Once the repository is public, that works with no token.

## Non-goals

v1 does not replace the RIP. Color, ICC profiles, and the RIP's own registration marks stay in the RIP.

v1 does not take orders, price the job as a product, or drive the printer or cutter directly. The design-PC draft adds a local material list with manually entered available roll length; it does not infer printed stock use or automatically deduct inventory. The readiness draft adds local workload observations as a foundation for OUTPUT; it does not add order management or printer completion tracking.

v1 does not nest on a website. There is no account and no cloud queue.

v1 does not send customer artwork anywhere. Joining OUTPUT is not part of v1.

## Privacy

Ez Nest is local-first. Nothing leaves the shop unless the shop opts in.

The server listens on `127.0.0.1` by default. Shop network is a separate choice. It accepts connections from other shop PCs only when started with `--lan`. An explicit installer choice can add this flag to the boot task. A saved preference alone cannot open it. Do not share that network with guest WiFi. There is no login on the page.

Update checks talk only to the configured GitHub release, and only while updates are on. A token is optional. A public repository does not need one.

Join OUTPUT network is off. The switch sends nothing. If a shop turns it on later, the only things shared would be the machine list and free capacity, and only after that opt-in.

Local activity records prepared frozen packs, successful hot-folder delivery, and
explicit removal from the hot folder. It stores an opaque pack ID, UTC event time,
piece count, dimensions, material area and artwork area in `workload.sqlite3` in
the app data directory. No filenames, artwork, customer details, or folder paths
are included. Records older than 90 days are pruned when recording new activity.
Settings shows the last 24 hours. Re-sending the same frozen pack counts once;
removal is a separate observation, not proof that printing was cancelled.
Downloads alone do not count as a hot-folder delivery.

These are demand signals, not printer utilization or free capacity. No records
are transmitted to OUTPUT, even if its placeholder switch is enabled. Future
sharing requires a separate, explicit opt-in.

The draft Illustrator pilot adds an explicit local production-copy handoff.
It copies selected artwork, organizes separate cut strokes into `thru-cut` and
`kiss cut` layers with artwork on `print`, and exports using an operator-selected
Adobe PDF preset. Regular is the only configured material. It does not generate
bleed, repair clipping groups, register templates or apply production color
substitutions. The handoff stores a local PDF and hashed source reference; it is
not an OUTPUT transfer. Recalculating a handoff with the same production settings
is one workload observation. A fresh Illustrator export is a new attempt.
The Nest in eznest script remembers the selected PDF preset, material, width and
existing bleed per Windows user. Later exports open directly in an empty browser
workspace; operators choose sets, review and send. Existing jobs require explicit
replacement. EZ Nest Settings changes those choices. The bridge is same-PC only.

## Roadmap

1. **v1 shop test.** EZ Designs runs the release candidate on the shop PC, beside the current workflow.
2. **Open source.** The repository is public, the license is MIT, and a shop can install, update, and report a problem with no token.
3. **OUTPUT opt-in.** A shop can join the OUTPUT print production network. Only the machine list and free capacity would be shared, and only after the shop opts in.

## Design-PC material and nesting draft

The simple browser page stores named roll presets in that browser: Moto Regular,
Moto Holographic, Moto Chrome and presets created with Add material. Holographic and
Chrome require the operator to save their dimensions and spacing before use.
These are nesting settings only; they do not configure ink, ICC profiles, Adobe
PDF presets or specialty preparation rules. The Illustrator pilot still supports
only Regular preparation.

A preset includes printable and roll width, spacing, edge/mark clearance, rotation,
sheet limit and an optional manually updated length left on that roll. Blank
remaining length means unknown, not unlimited inventory. A nest must fit a known
remaining length. Preparing, downloading or delivering a pack never deducts it.
The list is stored in browser preferences, not synchronized inventory across PCs.

Before splitting a job into conservative rectangular bins, the sheet allocator
tries all contours together when their total area can fit on one sheet. The
independent geometry checks still require every piece, allowed rotation, spacing
and sheet boundaries. This is a best-found layout, not a proven optimum.

The simple page uses a 30-second search budget with up to three different starts,
retaining the shortest independently checked layout. Geometry preparation and
validation can add time. Try tighter fit searches again without replacing a
shorter previous result, including when stopped early. Detailed search envelopes
may be simplified only when they provably contain the complete guarded artwork;
the original print objects and cut paths are unchanged. Saved rotation restrictions
remain in effect; any-angle rotation is an operator choice for suitable material.

The review screen defaults to the saved print folder and keeps the imported
filename. One-sheet PDF jobs save a named PDF; multi-sheet and SVG jobs save a
ZIP pack. My computer opens the normal Windows Save As window on the PC running
the app, with the filename suggested and no app-selected destination. Remote
clients use browser download instead. Settings has a separate folder chooser
for configuring the default print folder.
Cancelling the chooser does not claim success or deliver a file. Replacing different
bytes requires confirmation; previous bytes are retained under local app data in
export-backups. The legacy full-workspace pack delivery and Undo remain separate.

Saved material presets show a red Low stock notice at the configured alert
length, or 10% of the full roll when the alert is blank and full length is known.
Zero is Out of stock; unknown remaining stock does not generate an alert.
Remaining length and alerts are manual and local to this browser. Saving or
printing elsewhere does not automatically change stock.
