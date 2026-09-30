# eznest 0.11.0-beta.1 — Production-file beta

- PDF and PDF-compatible AI import with existing named cut contours.
- Piece/bleed review and PDF output retaining original artwork and CutContour.
- Customer, order and kit tracking across sheets and sorting checklists.
- Whole-piece sheet splitting and explicit material-only cost allocation.
- Comparison worksheet for same-job MX tests.
- Correct browser delivery lifecycle: failed fetches do not archive jobs.

SVG remains supported separately. No arbitrary native AI, DeviceN cut colors, EPS,
color conversion, automatic bleed, inventory or printer/cutter dispatch. Some PDF
structures are rejected; see docs/PRODUCTION-FILES.md. One material and 100 pieces
per batch. Actual ONYX/GoProduce and MX validation remain outstanding.

The portable Windows package is unsigned. Extract everything and keep _internal
beside eznest.exe. Preserve server data and browser storage when upgrading.
