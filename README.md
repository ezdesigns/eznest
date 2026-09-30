# eznest

A local nesting tool for Windows: **add SVG artwork → set roll width and quantities → nest → export**.

**0.10.0-beta.1 · SVG nesting beta.** The material fixes the roll width; eznest calculates the needed length. Files stay on your computer. Illustrator is not required for this workflow.

## What works

- Nest one or several jobs on a roll, preserving each job's complete sets.
- Set material width, contour gap, edge margin, allowed rotation and search time.
- Work in inches, millimeters or centimeters without resizing artwork.
- Fill spare space with complete optional sticker sets, up to the chosen maximum.
- Review the layout and locate pieces by job. Sorting IDs belong to a separate map.
- Export an SVG package to Downloads or a selected local folder. Reopen exported batches and restore jobs to the queue.
- Share material presets and shop output requirements as JSON files.

The MVP handles one material and up to 100 pieces per batch. Its search is heuristic; it does not guarantee the global optimum.

## Run the Windows download

If a Windows release has been attached to this repository, open **Releases** and download `eznest-0.10.0-beta.1-windows-x64.zip`. Extract the whole ZIP and open `eznest.exe`. Keep `_internal` beside it. This unsigned portable beta includes Python and its engine.

The GitHub **Code → Download ZIP** button downloads source code. Use the attached **Windows ZIP under Releases** when you want the runnable app.

Your browser opens `http://127.0.0.1:8765/`. Drop SVG artwork, check width and quantities, select **Nest**, then **Export SVG**. **Help → Quit eznest** stops the app; closing the tab alone leaves it running. See [the operator guide](START%20HERE.txt).

## Current format limits

SVG is the only implemented artwork format. Outline text, embed images and provide complete pieces with unambiguous boundaries. Export includes:

| File | Purpose |
| --- | --- |
| `artwork.svg` | Nested artwork at physical size |
| `sheet-map.svg` | Separate piece IDs and job map |
| `sorting-guide.html` | Human-readable sorting guide |
| `piece-checklist.csv` | Piece counts and identities |
| `batch.json` | Batch metadata and output requirements |
| `READ ME.txt` | Export notes |

**AI/PDF artwork import, production PDF/EPS output, CMYK conversion, automatic bleed, named cut-spot export and multi-sheet splitting are unfinished.** ONYX profiles expose those missing requirements; their exports are working SVG files and jobs stay active. This is not yet a verified ONYX/GoProduce print-and-cut handoff.

## Run from source

Use **Python 3.12, 64-bit, on Windows**. Double-click `Start EZ Nest.cmd`; it creates a local environment and installs the pinned dependencies on first use. Or run from the repository folder:

```powershell
py -3.12 -m venv .local/venv
.local/venv/Scripts/python.exe -m pip install -r requirements.txt
.local/venv/Scripts/python.exe launcher.py
```

Stop an older eznest version before starting another on port 8765. Developer options include `--no-browser`, `--port 8766`, and `--data-dir "path to test data"`.

## Test and build

Node is needed only for the JavaScript checks; there are no npm dependencies.

```powershell
.local/venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
node --check queue-app.js
node tests/test_queue.cjs
node tests/test_shop_profiles.cjs
node tests/test_boundaries.cjs
```

The included GitHub Actions workflow runs these checks on Windows for pushes and pull requests. Its first hosted result will be available after the repository is uploaded.

To build the portable Windows folder:

```powershell
.local/venv/Scripts/python.exe -m pip install -r requirements-build.txt
.local/venv/Scripts/python.exe build_windows.py --out ../eznest-build
```

Choose a **new build directory outside the source tree**. The output is `../eznest-build/dist/eznest`. Zip that complete folder for a release. Preserve its runtime, license notices and covered source.

## Repository map

| Location | Responsibility |
| --- | --- |
| `production.html`, `queue.css`, `queue-app.js` | Main interface and browser queue |
| `svg-io.js`, `queue-core.js` | SVG pieces, quantities, units and material composition |
| `engine.py`, `nesting.py` | Required nesting, validation and optional sticker fill |
| `server.py`, `launcher.py` | Local API, startup and isolated worker processes |
| `production.py` | Sorting manifest and frozen export packages |
| `folder_queue.py`, `output_folder.py` | Optional source watching and destination saves |
| `shop-profiles.js`, `shop_profiles.py` | Shared shop requirements and capability checks |
| `tests/` | Synthetic engine, API and queue fixtures |
| `jsx/`, `classic.html`, `app.js` | Earlier experimental Illustrator bridge; outside the standalone MVP |
| `licenses/` | Third-party notices and required upstream source |
| `.github/workflows/test.yml` | Windows CI checks |

`production.html` is the served entry point; `index.html` mirrors it. There is no bundled Illustrator extension installer in this repository.

## Data and handoff

Browser storage holds queue, presets and history. The local server stores its latest result and frozen exports in `.local/` for source builds or `data/` beside the portable executable. Keep exports backed up and use the same browser/address. Changing browsers does not transfer the queue.

The source handoff excludes workstation state, customer artwork, generated print packs, installed environments and private shop notes. The `.gitignore` excludes common local data and build output; place new customer files outside the repo or inside `customer-files/`.

- [GitHub walkthrough](docs/GITHUB-WALKTHROUGH.md)
- [Architecture and developer handoff](HANDOFF.md)
- [Packaged-app validation](PACKAGED-VALIDATION.md)
- [Repository handoff checks](docs/REPOSITORY-CHECK.md)
- [Release notes to paste into GitHub](RELEASE-NOTES.md)
- [Third-party notices](THIRD_PARTY.md)

No open-source license has been selected for the original eznest code. Keep the initial repository private while that choice is made. Included third-party components retain their own licenses. No MX Production Suite code, assets or binaries are included.
