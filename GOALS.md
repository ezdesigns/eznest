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

The simple page offers Quick (5 seconds), Balanced (30 seconds, default), and
Best fit (90 seconds). Longer budgets try up to three different starts,
retaining the shortest independently checked layout. Geometry preparation and
validation can add time; more search time does not guarantee an improvement.
Effort is saved in this browser and applies to the next search. Check pieces is
an optional gallery of detected artwork, copies, cut types and retained groups.
Try tighter fit searches again without replacing a shorter previous result,
including when stopped early. It shows measured length savings against the first
fit for unchanged quantities, not against a manual or competitor layout. A new
job/settings calculation starts a new comparison. Detailed search envelopes
may be simplified only when they provably contain the complete guarded artwork;
the original print objects and cut paths are unchanged. Saved rotation restrictions
remain in effect; any-angle rotation is an operator choice for suitable material.

Existing bleed remains part of the protected artwork envelope. The simple page
does not permit printed bleed to overlap another piece. Cut-line spacing alone
cannot prove that overlaid ink will preserve neighboring artwork or cut tolerance.
An extra blank export margin does not by itself join independent pieces: they can
separate when every export guard excludes the other protected paint cores and
each unit has its own cuts. The original guards remain around exported artwork;
search simplification never enlarges the export clip. Truly connected paint and
ambiguous nearby decoration remain grouped. Existing saved jobs retain their
previous geometry; re-import the original prepared file to use new grouping.

PDF cut validation understands compound clipping masks using their original
nonzero or even-odd fill rule. It checks whether each cut stroke is visible;
an enclosed hole does not make an otherwise visible contour invalid. Closed,
exactly collinear slits retain their original commands as internal cuts and
still require a unique enclosing piece. Self-intersecting piece boundaries,
genuinely clipped cuts and unowned cuts remain blocked. Source masks, artwork
and cut commands are not repaired or redrawn. A file with no detected cuts
gets a distinct message to check its spot names or layer mapping.

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

## Tester review and feedback

The review card compares roll length against an operator-entered previous print
length for the same material, width and quantities, or against the first fit of
an unchanged job during tighter-fit attempts. It does not claim a manual or
competitor saving without that reference. Full roll cost and full roll length
provide a USD material-only estimate; ink and labor are excluded. Negative
comparisons show more material used. Unused space means the printable sheet area
outside protected artwork envelopes, including gaps and margins; it is not ink
coverage or money saved. Piece cards retain imported names (including SVG object
names); PDFs without usable piece names use numbered page/piece/group labels.

First run accepts an empty printer and default folder for local-save testing.
Send feedback opens a previewable GitHub issue draft or saves a local text report.
Version and the operator's message are included. Result counts, dimensions,
unused space and timing require a checkbox that starts unchecked each time.
Customer files, names, paths and job identifiers are never attached automatically.
Private-repository feedback requires repository access. OUTPUT remains disabled.

The separate per-user tester installer is defined by installer/tester.iss and
packages a verified portable trial. It has its own AppId and a build-specific
installation folder, creates no service/task/firewall rule, and launches with
--shop-test. This is not proof of a clean-PC install or physical print/cut
acceptance. Those checks must be reported separately for the exact build.
