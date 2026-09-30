# Production files in 0.11.0-beta.1

The MVP works without hardware details. Enter usable width; optionally configure
sheet length, bleed, material cost and a shop profile. Equipment-specific validation
is an operator task, not an onboarding requirement.

## PDF / AI

AI must contain the PDF representation created by Illustrator's Create PDF Compatible
File option. The importer reads that representation, not proprietary Illustrator
editing data. Closed stroked /Separation paths identify pieces, usually CutContour.
Ordinary magenta lines are not cut spots. Multiple pages, cubic curves, rotated
pages, transformed/reused forms and static all-visible PDF layers are supported.

Enter existing bleed in millimeters at import. Zero clips at the cut; a positive
value reserves an outward envelope. It does not create missing ink. Review every
detected piece and confirm its size, completeness and bleed before nesting.
This is operator review, not automated ink-coverage verification. Re-add a file
to change the bleed allowance.

Print PDF export copies original drawing objects/resources into clipped Form
XObjects. Preview pixels are never print artwork. Existing cut strokes are removed
from those forms and the original geometric paths are emitted in a named spot
separation and separate layer, transformed with the artwork. Source color spaces,
fonts, images and compatible output intents are preserved. Conflicting embedded
output profiles are rejected on export; eznest does not convert colors.

Unsupported content fails closed: encrypted files, non-PDF AI, annotations/forms,
hidden/conditional layers, nonstandard UserUnit, missing/open/compound/self-crossing
contours, clipped contours, overlapping bleed regions or pieces outside the page.
DeviceN cut colors are unsupported. Limits: 20 MB, 25 pages and 100 contours/copies.
This is narrower than arbitrary PDF/AI compatibility.

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

## Sheets and costs

Settings > Sheets and material cost contains the optional per-sheet length limit,
independent of total available roll length. Whole pieces are allocated to feasible
sheets; Sparrow attempts to improve each. A failed/worse solve retains the valid
fallback. Pieces are never divided. Kits may span sheets but their batch counts
and sorting identities remain intact. The allocator is conservative and heuristic;
it does not jointly optimize all bins and may waste space on narrow/concave parts.

Optional complete sticker sets fill spare space across sheets within the global
100-piece cap. Fixed-length sticker-only fill stays a single-sheet operation.
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
browser queue during upgrades. Frozen output packages never change after export.
Folder delivery completes after safe file writes. Browser delivery completes after
fetching the ZIP and starting its download, not after physical printing or confirmation
of a user's disk-save choice. Failed fetches leave jobs active; retries reuse the
same frozen package.

Layout details > Download comparison worksheet records sources/revisions, settings,
counts, sheets, length and elapsed search time, with empty MX and physical-output
fields. It does not run MX or claim superiority. Compare the same jobs/settings
and validate size, artwork, cut mapping, registration and kit completeness in the shop.
