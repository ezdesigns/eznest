# Production files in 1.0.0-rc.4

The MVP works without hardware details. Enter usable width; optionally configure
sheet length, material cost and a shop profile. Equipment-specific validation
is an operator task, not an onboarding requirement.

## PDF / AI

AI must contain the PDF representation created by Illustrator's Create PDF Compatible
File option. The importer reads that representation, not proprietary Illustrator
editing data. Cut strokes are identified by configurable Separation spot names
or visible PDF layer names. Color alone does not identify a cut. Outermost closed
cut boundaries define pieces; contained open/closed cut paths stay attached to them.
A kiss-only closed boundary is valid. Separate pieces nested inside another piece
are not inferred: separate them in the source before import. Multiple pages, cubic curves, rotated
pages, transformed/reused forms and static all-visible PDF layers are supported.
Illustrator layer CreatorInfo metadata is accepted; print/view visibility rules
remain unsupported. Native editing metadata is omitted from the local PDF print
source. Previews share that source across pieces; exported artwork stays vector.

The simple shop page automatically reserves the full prepared artwork, including
existing bleed, using PDF paint paths and clipped object bounds. Nesting and gap
checks use that outer envelope, with a conservative clearance guard; they do not
use the cut line as the print edge. Original PDF paint and cut geometry keep their
scale. No bleed amount or artwork enlargement is applied. Connected or very close
artwork stays together as a group, and detached artwork without a cut owner blocks
import instead of being discarded. Conservative envelopes can use extra material.

Review every detected piece and confirm its size, completeness and bleed before
printing. The legacy full workspace/API still supports an explicit bleed envelope;
old simple-page layouts must be re-imported from the original prepared file.
Re-add a file to change input cut mapping. Per-piece operation counts are
shown during review. Generic CutContour without a mapped type requires an explicit
choice in the import screen: thru, kiss, or generic for manual RIP assignment.

Print PDF export copies original drawing objects/resources into clipped Form
XObjects. Preview pixels are never print artwork. Existing cut strokes are removed
from those forms and all original cut paths are emitted once under the configured
spot separation and layer for their operation, transformed with the artwork. Source color spaces,
fonts, images and compatible output intents are preserved. Conflicting embedded
output profiles are rejected on export; eznest does not convert colors.

Unsupported content fails closed: encrypted files, non-PDF AI, annotations/forms,
hidden/conditional layers, nonstandard UserUnit, missing boundaries, conflicting
mappings, orphan open cuts, duplicate cuts, intersecting closed boundaries without
a unique owner, filled/dashed cut shapes, clipped cuts, overlapping explicit bleed regions
or pieces outside the page. DeviceN cut colors are unsupported.
Limits: 32 MB, 25 pages, 800 pieces/copies per batch, 2000 cut paths per page,
5000 per document, 5000 sampled points per path and 1,000,000 traversed drawing
operators per page.
This is narrower than arbitrary PDF/AI compatibility.

Refreshing the shop page restores file rows, per-file sets and the saved layout's
nesting settings, including while a search is running. To change a PDF's input
cut mapping after refresh, start over and re-add its original file; the browser
does not retain access to the original file picker selection.

Source clipping is not redaction. Original referenced drawing objects may remain
behind clips in exported PDFs. Use print-only sources without content that must
be irrecoverably removed. Inputs are never edited.

## Formats and profiles

PDF/AI jobs nest together and export PDF; SVG jobs nest separately and export SVG.
Mixing them would require a separately validated artwork converter. Folder watching
is still SVG-only; use file selection/drop for PDF and AI.

Choose Preserve source colors. Leave printer color management and registration
marks to the RIP. Existing custom profiles remain unchanged on upgrade. An older
ONYX profile requiring CMYK conversion will remain unmet until the operator chooses
Preserve source colors. Required bleed is explicit. No EPS conversion, automatic
bleed or printer/cutter dispatch is implemented. ONYX/GoProduce profiles do not
certify equipment compatibility.

Cut type mappings use exact case-sensitive spot/layer names or explicit prefixes.
For each source name, exact rules override prefix rules. Conflicting operations
across a spot and any containing layer stop import. Unrecognized names matching
a suspect prefix also stop import; unrelated brand spots are retained. An unknown
cut name outside those prefixes cannot be identified automatically.

Defaults include reported LNThru-cut/LNKiss-cut/LNRegmark as optional literal
aliases, alongside Thru-cut/Kiss-cut/Regmark and common CutContour variants. The
shop page writes CutContour_Thru-cut and CutContour_Kiss-cut unless the operator
picks the LN preset. These are starter recognition rules, not cutter commands.
Tool notes are informational only. Output spots and layers must be distinct for
each operation; configure ONYX/GoProduce to recognize the chosen names.

Known registration paint is stripped before nesting, including recognized vector
marks, Form/Image objects and text. Registration text advances are retained without
painting. Marks with unrecognized names or embedded in ordinary print images cannot
be detected: use print-only sources and review. Old marks are never generated by
eznest; choose RIP/finishing registration if marks were removed. Input files stay intact.

## Sheets and costs

Settings > Sheets and material cost contains the optional per-sheet length limit,
independent of total available roll length. Whole pieces are allocated to feasible
sheets; Sparrow attempts to improve each. A failed/worse solve retains the valid
fallback. Pieces are never divided. Kits may span sheets but their batch counts
and sorting identities remain intact. The allocator is conservative and heuristic;
it does not jointly optimize all bins and may waste space on narrow/concave parts.

Optional complete sticker sets fill spare space across sheets within the global
800-piece cap. Fixed-length sticker-only fill stays a single-sheet operation.
Multi-sheet batches export numbered files, not one overly long print file.
PDF pages are limited to 5000 mm per side; set a per-sheet length limit for longer batches.

The map shows sheet boundaries. CSV/JSON include customer, order, kit, set, piece,
sheet number, local sheet coordinates, and batch coordinates. Batch y coordinates
stack sheets vertically for preview only.

Optional price is entered per square meter with a three-letter currency code.
Batch material area is width times summed sheet lengths. Per-job cost shares all
material (including waste) in proportion to occupied piece area, including reserved
bleed. Rounded amounts reconcile to the batch total. Ink, laminate, labor, overhead
and profit are excluded; this is not a selling quote.

## Delivery and comparison

Server-side data/documents contains imported PDFs/metadata. Preserve it with the
browser queue during upgrades. Imports from before 0.12 need re-adding and review
because they did not record multiple cut operations. Frozen packages remain valid
within their original release scope and are not regenerated. Frozen output packages never change after export.
Folder delivery completes after safe file writes. Browser delivery completes after
fetching the ZIP and starting its download, not after physical printing or confirmation
of a user's disk-save choice. Failed fetches leave jobs active; retries reuse the
same frozen package.

Layout details > Download comparison worksheet records sources/revisions, settings,
counts, sheets, length and elapsed search time, with empty MX and physical-output
fields. It does not run MX or claim superiority. Compare the same jobs/settings
and validate size, artwork, cut mapping, registration and kit completeness in the shop.
