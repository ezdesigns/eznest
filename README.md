# eznest

**Add artwork → set material width and quantities → nest → review → export.**

**0.12.0-beta.1 · Windows mixed-cut beta.** Standalone local nesting for
complete kits, decals and stickers. Illustrator, a printer model and an account
are not required. Width comes from the material; length comes from the layout.

## What works

- PDF and PDF-compatible AI with mapped spot/layer cut strokes and closed piece boundaries.
- Original PDF drawing objects retained. Thru-cut, kiss-cut and generic cuts have
  separate configurable output spots/layers. Preview pixels never become print art.
- Interior open/closed cuts move with their piece through rotation, copies and sheets.
- Shareable cut mappings, per-piece counts and removal of recognized old registration marks.
- SVG import/export in separate batches.
- Review detected pieces, physical sizes and existing bleed before nesting.
- Complete-set quantities, mixed jobs, customer/order/kit identity and sorting maps.
- Optional whole-piece sheet splitting and numbered print files.
- Complete-set sticker fill, reusable material presets and configurable units.
- Optional material cost per job with explicit allocation of shared unused material.
- Frozen ZIP/folder export, history, re-queueing and an MX comparison worksheet.

One material and up to 100 pieces per batch. Nesting and sheet allocation are
heuristic, not guaranteed global optima. Read [supported files and limits](docs/PRODUCTION-FILES.md).

## Important limits

PDF import needs cut strokes mapped by Separation spot or visible PDF layer.
An outer closed path owns contained interior cuts; unrelated nested pieces are not
inferred. Unknown/conflicting cut names stop import. Enter existing bleed; eznest
does not generate it or certify ink coverage. Unsupported hidden layers,
annotations and ambiguous contours are rejected. Arbitrary native AI and DeviceN
cut colors are not supported. PDF import is limited to 20 MB and 25 pages.

PDF and SVG jobs cannot be mixed in one batch. Watched folders remain SVG-only.
Use Preserve source colors; configure printer ICC/color conversion and registration
marks in ONYX/your RIP. No EPS, automatic bleed, inventory or printer/cutter dispatch.
**Physical ONYX/GoProduce validation and controlled MX comparison remain outstanding.**

## Run on Windows

Extract the entire portable ZIP and open eznest.exe. Keep _internal beside it.
This unsigned beta includes its runtime. GitHub's Code → Download ZIP is source,
not the runnable application. See [START HERE.txt](START%20HERE.txt).

For source, use **Python 3.12 x64** and run Start EZ Nest.cmd, or:

```powershell
py -3.12 -m venv .local/venv
.local/venv/Scripts/python.exe -m pip install -r requirements.txt
.local/venv/Scripts/python.exe launcher.py
```

The browser opens http://127.0.0.1:8765/. Stop an older version on that port first.
Developer options: --no-browser, --port 8767, --data-dir "isolated test folder".

## Run the web page

The simple page is one screen: drop a file and it nests. Change the material or the sets and it nests again, then Send to ONYX.
It uses the same local Python server as the Windows app. Nesting stays on this computer.
There is no account. SVG is the first format. PDF and PDF-compatible AI use the existing
cut-spot importer. The full workspace remains at `/`.

From source, with Python 3.12:

```bash
python3 -m venv .local/venv
.local/venv/bin/pip install -r requirements.txt
.local/venv/bin/python launcher.py --web
```

On Windows, use `.local\venv\Scripts\python.exe launcher.py --web`.
Then open http://127.0.0.1:8765/web. `--no-browser` prints the address without opening one.
Drop `sample-artwork.svg` on that page. It nests on its own.

Docker, from this directory:

```bash
docker build -t eznest .
docker run --rm -p 8765:8765 eznest
```

Open http://127.0.0.1:8765/web. The server still accepts only loopback host names.
Publish port 8765, or the page will refuse the request.

Send to ONYX writes one frozen package. Sending again, or opening the page again after a
restart, returns that same file and the same SHA-256. The layout id and hash stay in that
package. The page shows material used, waste, and sheets.

Not in this page: automatic bleed, an ONYX or GoProduce proof, laminate cost, and
the later pro pass that batches work by time. PDF import is still 20 MB, 25 pages,
named spots or layers, and no DeviceN, native AI, or EPS. SVG and PDF cannot share
a batch. One batch holds 100 pieces. See [supported files](docs/PRODUCTION-FILES.md).

## Test and build

Node is only needed for checks; there are no npm dependencies.

```powershell
.local/venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
node --check queue-app.js
node --check production-features.js
node tests/test_queue.cjs
node tests/test_shop_profiles.cjs
node tests/test_cut_mapping.cjs
node tests/test_production_features.cjs
node tests/test_boundaries.cjs
.local/venv/Scripts/python.exe -m pip install -r requirements-build.txt
.local/venv/Scripts/python.exe build_windows.py --out ../eznest-build
```

GitHub Actions runs the checks on Windows, Python 3.12 and Node 24. Use a new
build directory outside the source tree. Zip its complete dist/eznest folder.

## Repository map

| Files | Purpose |
| --- | --- |
| production.html, queue.css, queue-app.js, production-features.js | Interface and production controls |
| queue-core.js, svg-io.js | Identity, quantities, units, presets and SVG |
| pdf_io.py | Piece ownership, cut detection, previews and original-object PDF output |
| cut_mapping.py, cut-mapping.js | Shareable cut rules, names and validation |
| engine.py, nesting.py, sheets.py | Nesting, validation, filler and sheets |
| production.py, costing.py | Packages, sorting and material estimates |
| server.py, launcher.py | Local API and isolated workers |
| folder_queue.py, output_folder.py | SVG source watching and safe folder saves |
| shop-profiles.js, shop_profiles.py | Configurable output requirements |
| tests/ | Geometry, renderer, HTTP API and queue checks |

production.html is served; index.html mirrors it. jsx/, classic.html and app.js
are an earlier Illustrator experiment outside this standalone MVP.

## Data and ownership

Queue/history use IndexedDB; settings use localStorage. Server data lives in
.local/ for source builds or data/ beside the portable executable. Preserve
documents/, frozen batches and browser storage when upgrading. Re-add active PDF/AI
jobs imported before 0.12 to review their cut types; old frozen packages stay intact. Changing browsers
or ports does not transfer the queue. Exported never means physically printed.

Keep customer files outside the repo or in customer-files/. Runtime state,
environments and build outputs are ignored. Read [HANDOFF.md](HANDOFF.md),
[production behavior](docs/PRODUCTION-FILES.md), [validation](docs/PRODUCTION-VALIDATION.md)
and [mixed-cut workflow](docs/CUT-WORKFLOW-NEXT.md), [0.12 validation](docs/MIXED-CUT-VALIDATION.md), plus [third-party notices](THIRD_PARTY.md). PACKAGED-VALIDATION.md and HANDOFF-MANIFEST.json record the older 0.10 release.

## Open-source license

Recommended license for original eznest code: **MIT**. It matches the permissive
terms already used by Sparrow (MIT), pypdf (BSD-3-Clause), Pillow (MIT-CMU), and
charset-normalizer (MIT). Two dependencies need to stay beside that choice:

- jagua-rs is MPL-2.0. Its license is file-level. eznest uses the unmodified
  library through spyrrow and already ships `licenses/jagua-rs-0.7.0-source.crate`
  with its notices. Do not copy MPL source into eznest files without keeping those
  files under MPL.
- Shapely links GEOS, which is LGPL-2.1. The pip and Docker installs use GEOS as a
  separate library, and `licenses/geos-3.13.1-source.tar.bz2` is the corresponding
  source. Replacements can follow the note in [THIRD_PARTY.md](THIRD_PARTY.md).
  Do not statically absorb GEOS into a build that users cannot relink.

Rajdhani and Red Hat Display on the web page stay under the SIL Open Font License
in `fonts/`. That license does not cover the application.

MIT has not been applied. This repository stays private until that decision is made.
Dependencies keep their own licenses. No MX source, assets, or binaries are included.
