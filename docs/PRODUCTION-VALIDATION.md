# Production-file beta validation

Version 0.11.0-beta.1, checked on Windows 11 x64 on 2026-09-30.
No printer/cutter model was needed to configure or run the MVP.

## Automated source checks

- 54 Python tests passed, including original SVG/queue/server coverage.
- All four Node suites passed: queue/units, profiles, production features and
  boundary policy. Interface JavaScript syntax checks passed.
- Synthetic PDF fixtures exercise real Separation cut strokes, cubic paths,
  reused/transformed forms, rotated pages, source CMYK operators, all-visible
  layers, review/tamper checks, open/overlapping/conditional-contour rejection,
  PDF sheet dimensions, exact cut paths and independent PDFium pixel rendering.
- A real HTTP integration test runs import and nesting workers, PDF export,
  download acknowledgment and byte-identical frozen-package retry. Failed/stale
  acknowledgment cannot complete the current batch.
- Sheet tests check complete quantities, bounds/spacing, total roll limits,
  complete optional sticker sets, separate SVG sheet positions and cost rounding.

## Browser check

Used an isolated data directory and browser port, preserving the shop's older
running app and its queue. Imported synthetic PDF and PDF-compatible .ai files
through the actual file picker. Reviewed thumbnails with 1 mm existing bleed,
assigned two customer/order identities, combined 10 pieces, and exported seven
sheets. The test used deliberately small 80 mm stock and a 40 mm sheet limit.
The result used 232.94 mm in total; the material estimate was USD 0.33 at
17.50/m², allocated as USD 0.20 and USD 0.13. These are test values, not shop defaults.

The queue grouped orders, sorting IDs and sheet separators appeared in preview,
and successful browser delivery moved jobs into Exports. No browser warning/error
logs were recorded. Three numbered PDF sheets from an earlier six-piece browser
batch were rendered with Poppler and visually checked for size, bleed and contours.

## Portable Windows check

Built with Python 3.12.14, PyInstaller 6.22.3 and hooks 2026.7, using pinned runtime
requirements. The portable executable was launched with its own fresh data folder.
`tests/portable_smoke.py` exercised the packaged PDFium renderer, document worker
and native nesting worker without relying on an installed application runtime.

The executable imported two synthetic sources, nested eight pieces from two
orders into six bounded sheets, and saved a complete folder/ZIP package. Verified:

- PDF 1.7 output, physical page width and maximum sheet length;
- a named CutContour Separation and separate CutContour layer;
- all eight exported contours re-read from the finished PDFs;
- customer/order identity, material-cost reconciliation and safe folder delivery;
- identical package bytes on retry and rejection of non-PDF Illustrator data.

All distinct exported sheet layouts were independently rendered with Poppler and
visually inspected. Runtime, DLLs and third-party notices are included in the ZIP.
The application remains an unsigned portable beta, not an installer.

To repeat the packaged check after building, use a new test directory:

```powershell
python tests/portable_smoke.py --exe ../eznest-build/dist/eznest/eznest.exe --work .local/new-portable-check
```

## Not established by these checks

No customer kit was physically printed, laminated or cut. No ONYX/GoProduce RIP
run or controlled MX comparison was performed. The comparison worksheet is a
recording aid, not a benchmark result. Synthetic tests do not establish arbitrary
Illustrator/PDF compatibility, ICC correctness, bleed ink coverage or global nesting
optimality. See [supported files and limits](PRODUCTION-FILES.md).

Use the same representative print-only kit and settings in eznest and MX, then
record material length, operator time, actual size, contour mapping, cut alignment
and complete kit counts before deciding whether eznest is production-ready for a shop.
