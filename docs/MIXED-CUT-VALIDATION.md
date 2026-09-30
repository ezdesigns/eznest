# Mixed-cut beta validation

eznest 0.12.0-beta.1, Windows 11 x64, 2026-09-30.
This evidence uses synthetic artwork; actual shop file and equipment validation
remain outstanding. The earlier production-file report records the 0.11 baseline.

## Source checks

- 63 Python tests passed, including nine mixed-cut cases and the real HTTP worker
  import/nest/export lifecycle. The final handoff-text addition passed the nine
  mixed-cut cases again.
- Five Node suites passed: queue/units, shop profiles, production features,
  boundary policy, and cut mapping/profile sharing. Interface syntax passed.
- Fixtures exercise layer-only and spot-only recognition; generic type choices;
  conflicting rules and exact-over-prefix precedence; open Bezier interior cuts;
  closed interior kiss cuts; reused/nested/transformed Forms; duplicate/orphan/
  overlapping cuts; unsupported DeviceN/dashed/clipped cuts; registration vector,
  Form, Image and text paint; and old metadata requiring re-import.
- Export/re-import checks four copied/rotated pieces over two sheets, exact
  operation counts, relative cut geometry, distinct spot/layer names, untouched
  brand ink, CSV/checklist counts, and custom output names without tool commands.

## Browser check

Used an isolated port and data directory, preserving the older shop app.
Imported a two-piece synthetic PDF through the file chooser with 1 mm existing
bleed. Each review thumbnail showed one thru-cut and two kiss-cut paths. The
review disclosed removal of two old registration paint objects. Confirmed piece
review, two complete sets, editable/shareable profile controls and nest/export.

The four-piece browser layout reported four thru paths and eight kiss paths;
export moved the job into Exports. The download event observer timed out, while
the page reported download started and the frozen batch remained available.
Disk-delivery verification was performed separately by the packaged test below.
Screenshots were saved locally as eznest-mixed-cut-review.jpg and
eznest-mixed-cut-export.jpg outside the repository.

## Packaged executable

Built with Python 3.12.14, PyInstaller 6.22.3 and hooks 2026.7 using pinned runtime
dependencies. Ran tests/portable_smoke.py against the actual executable with a
fresh external data folder. The final r2 build imported two synthetic sources,
including repeated nested Forms, and nested two orders / eight pieces into eight
deliberately constrained sheets (80 mm width, 40 mm maximum sheet length).

Verified PDF 1.7, physical sheet dimensions, eight thru paths and sixteen kiss
paths, one of each operation layer, no old registration paint, complete order
identities, folder writes, identical retry bytes, non-PDF AI rejection and material
cost reconciliation. Total sheet length was 294.43556 mm; the test material
estimate was USD 0.41 at USD 17.50/m². These are test values, not shop defaults.

All eight finished PDFs were independently rendered at 160 DPI with Poppler and
visually inspected. Artwork and interior cuts remained aligned; the cyan print
and unrelated magenta brand artwork were retained, without old black marks.
The test app shut down cleanly. Runtime and licenses are included in the complete
portable ZIP; its data directory is not bundled.

Delivered archive: eznest-0.12.0-beta.1-windows-x64.zip, 42,679,224 bytes.
SHA-256: 984feda4d0b244620c81467256a98d63a153f184b8f9bd29d08b64aa71599739.

## Still unverified

No matched customer AI/PDF/cut set has been inspected for this release, and no
physical ONYX/GoProduce print/cut or controlled MX comparison has been performed.
Reported LN names are editable starter aliases; their literal source usage and
reported SP selections remain unconfirmed. Separate output layers and spots do
not certify the active RIP's method mapping. Unknown marks within ordinary art
and independent pieces nested inside another boundary require source preparation.
