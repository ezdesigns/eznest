# eznest 0.10.0-beta.1

The MVP is a standalone SVG nesting workspace for Windows: add artwork, select quantities and roll width, nest, then export. Optional sticker fill uses leftover space. Inventory and automatic cleanup of complete design files are outside this release.

## Running

For operators, extract the Windows package and open eznest.exe. See START HERE.txt. The package is portable, unsigned, and includes Python and the geometry engine. It opens the user's browser on a loopback-only server. No account or subscription is required by this build.

For development, install Python 3.12 x64 and run Start EZ Nest.cmd. It creates .local/venv and installs requirements.txt when needed. To run manually:

```powershell
python -m venv .local/venv
.local/venv/Scripts/python.exe -m pip install -r requirements.txt
.local/venv/Scripts/python.exe launcher.py
```

The source launcher checks app identity and version before reusing a server. Stop the previous release before switching versions. Optional developer arguments: --no-browser, --port 8766, --data-dir "path to test data". Browser storage is separated by port.

## Supported export

An immutable batch package contains artwork.svg, sheet-map.svg, sorting-guide.html, piece-checklist.csv, batch.json, and READ ME.txt. Geometry is independently checked for bounds, overlap, spacing and required counts before release. Sorting IDs are separate from artwork. Originals remain intact.

SVG is the only implemented artwork format. There is no verified ONYX production handoff: PDF/AI artwork, CMYK conversion, bleed generation, named spot colors, cut layers and multi-sheet splitting still need engineering and real RIP/cutter validation. The ONYX requirements profile deliberately produces a working SVG and keeps jobs active. Profile edits describe requirements; they do not convert art. Matching a generic SVG profile is not full print preflight.

## Architecture

- production.html, queue.css, queue-app.js: interface, browser queue and export flow.
- svg-io.js: supported SVG import, piece artwork and transforms.
- queue-core.js: quantities, physical units, materials and saved-job lifecycle.
- server.py: loopback API, authenticated writes, frozen batches and isolated worker process.
- engine.py: spyrrow adapter plus independent geometry validation.
- nesting.py: required layout followed by bounded whole-set sticker fill.
- production.py: source identity, sorting manifest and six-file package.
- folder_queue.py / output_folder.py: source watching and safe destination writes.
- shop-profiles.js / shop_profiles.py: portable requirements and output capability checks.
- launcher.py: source/portable startup and packaged-worker dispatch.

Queue and history use IndexedDB; settings use localStorage. Server data is .local for source builds and data beside the portable exe. Browser queue storage is not a portable backup. No telemetry or external service is required to nest.

## Rebuild on Windows

Use Python 3.12 x64. Install requirements-build.txt into a clean virtual environment, then:

```powershell
.local/venv/Scripts/python.exe build_windows.py --out "C:/path/to/new-build-folder"
```

Use a new build folder outside this source tree. It produces dist/eznest with its _internal runtime. Zip the entire eznest folder, not just the executable. Included licenses/ contains upstream notices and jagua-rs covered source. Preserve all notices when distributing. Third-party packages remain under their respective licenses; no MX code, assets or binaries are used.

## Tests

```powershell
.local/venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
node tests/test_queue.cjs
node tests/test_shop_profiles.cjs
node tests/test_boundaries.cjs
```

SVG browser tests are at /tests/svg-tests.html only when EZ_NEST_TEST_UI=1 in a source build. Portable builds disable this switch. To verify a release, extract it to a path containing spaces, start with a separate data directory/port, import example artwork through the UI, nest, export and inspect actual files. Test reopening, saved-job history and shutdown. PACKAGED-VALIDATION.md records the release check.

## Next production milestone

Add a faithful PDF/AI artwork path and ONYX-compatible output with named CutContour spot/layer, then test actual shop files through ONYX and GoProduce at real size. Agree bleed and ICC requirements with the shop. Compare material use, time, quantities and fidelity against MX on the same jobs before making quality claims. The current heuristic does not guarantee a global optimum.
