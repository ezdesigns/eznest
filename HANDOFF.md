# eznest 0.12.0-beta.1 developer handoff

Read README.md and docs/PRODUCTION-FILES.md first. This standalone local Windows
beta adds mixed cut operations to production files, order identity, optional sheets and material estimates
to the existing simple nesting workflow. A printer/cutter model is not required.
Real ONYX/GoProduce and MX validation remain outstanding.

Mixed thru/kiss implementation and reported shop evidence are documented in
[docs/CUT-WORKFLOW-NEXT.md](docs/CUT-WORKFLOW-NEXT.md). Starter aliases are editable;
they are not proof of the shop's source names or active cutter settings.

The browser stores queue/history in IndexedDB and settings in localStorage.
PDF imports run in an isolated --document-worker process. Original PDF drawing
objects are preserved; preview PNGs never become print art. pdf_io.py extracts
mapped spot/layer strokes, groups contained cuts under outer closed boundaries,
preserves Bezier paths, and applies one transform to art and every owned operation.
Open interior cuts are retained; duplicates, conflicts and orphan paths reject.
Cut rules, generic handling and output names live in cut_mapping.py/cut-mapping.js.
Source visible OCGs are flattened after validation; output operations get new OCGs.
Known registration paint is removed; no tool commands or new marks are generated. Unsupported structures fail with a visible explanation.
Server-side metadata prevents altered browser contours replacing imported geometry.

engine.py wraps spyrrow and validates counts, bounds, rotations and spacing.
sheets.py produces feasible whole-piece sheets, attempts per-sheet improvements,
and validates both sheet-local geometry and batch-wide counts. nesting.py adds
optional complete sticker sets without moving required placements. Production
source identities survive splitting; kits may span sheets without losing pieces.

production.py writes frozen artwork, separate maps, order/customer checklists and
metadata. costing.py allocates full material cost by occupied area with exact cent
reconciliation. This excludes ink, laminate, labor, overhead and profit.

server.py owns batch readiness and delivery. Browser completion is acknowledged
after the ZIP fetch and download start. Folder saves complete only after safe
writes. Failed delivery leaves jobs active; retry does not regenerate a frozen pack.
Exports with unmet profile requirements are explicitly working packages and do not
archive jobs. Exported never means physically printed.

Use Python 3.12 x64 with pinned requirements; Node checks need no npm dependencies.
Run launcher.py with an isolated port/data directory for development. The Windows
builder bundles both document and nesting workers and all third-party notices.
New tests cover curves, CMYK objects, transformed forms, spot/layer output,
rendered placement, sheets, costs, and actual HTTP import/nest/export workers.

Keep original shop files outside source control. Preserve data/documents and browser
storage on upgrades. Metadata modelVersion 2 is required: old active PDF jobs must
be re-imported/reviewed, while frozen batches remain unchanged. Source clipping is not confidential-content redaction.

Next evidence: representative shop files with before/after rendering and dimensions,
then CutContour recognition, registration/cutting through the actual workflow,
and equal-settings MX comparisons. Do not claim arbitrary AI/PDF support or global
nesting optimality. Inventory, automatic design cleanup, EPS, color conversion,
automatic bleed and direct printer/cutter dispatch remain outside this milestone.
Legacy Illustrator bridge files are not the main application.
