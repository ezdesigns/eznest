# eznest

**Add artwork → set material width and quantities → nest → review → export.**

**1.0.0-rc.3 · shop release candidate.** Standalone local nesting for
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

One material and up to 800 pieces per batch. Nesting and sheet allocation are
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
marks in ONYX/your RIP. No EPS, inventory, or printer/cutter dispatch. The web page
can offset full-bleed artwork past the cut; it does not certify ink coverage.
**Physical ONYX/GoProduce validation and controlled MX comparison remain outstanding.**

## Run eznest in the shop

The shop page is one screen. Double-click starts it. There is no terminal and no account.

Packaged app (the folder that contains `eznest.exe`):

1. Copy the whole folder onto the shop PC. Keep `eznest.exe`, `_internal`, and `eznest-web.bat` together.
2. Double-click `eznest-web.bat`.
3. The browser opens http://127.0.0.1:8765/web. Drop the day's files, set each quantity, and Send to ONYX.

Source folder (this repository, with 64-bit Python 3.12 installed):

1. Double-click `eznest-web.bat`.
2. The first time, it creates `.local\venv` and installs the engine. That window can sit for a minute. Later double-clicks open straight away.
3. The browser opens the same address, http://127.0.0.1:8765/web.

If a message says another version is using port 8765, double-click `Stop EZ Nest.cmd`, or open the old window and use Help → Quit eznest. Then double-click `eznest-web.bat` again. A 0.12 server will not share the port with 1.0.0-rc.3.

Closing the browser leaves eznest running. Double-click `Stop EZ Nest.cmd` to stop it. Help → Quit eznest does the same from the full workspace.

Material, width, and cut spot names stay in that browser for http://127.0.0.1:8765. The hot-folder path stays there too, and on disk in `data\` (packaged) or `.local\` (source). Keep that folder when you update.

`eznest.exe` without the bat still opens the full workspace at http://127.0.0.1:8765/.

One shop computer runs eznest. The other computers only open a browser. Use the installer below for that computer. `eznest-web.bat` is still the one-PC start.

## Install on the shop server

The shop server is one Windows PC. The installer puts eznest in Program Files. That PC does not need Python or Git. GitHub Actions builds `eznest-setup.exe`, so nobody compiles it by hand.

The workflow is `.github/workflows/windows-installer.yml`.

- Push a `v*` tag, such as `v1.0.0-rc.3`. That run attaches `eznest-setup.exe` and `BUILD.json` to the GitHub release for the tag.
- Or open Actions, choose Windows installer, and run the workflow on this branch. That uploads `eznest-setup.exe` and `BUILD.json` as an artifact and does not publish a release. GitHub shows Run workflow after this file is on the default branch, or after the workflow has run once.

`BUILD.json` records the version, the commit SHA, and the SHA-256 of `eznest-setup.exe`. Compare the exe's SHA-256 with `sha256`, and compare `commit` with the git commit, before you install it. When `BUILD.json` sits next to `eznest-setup.exe`, the installer copies it into `C:\Program Files\eznest`. The portable folder's `BUILD.json` is a dependency list. The installer does not bake that copy in.

To build it on a Windows machine instead, install 64-bit Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
py -3.12 -m pip install -r requirements.txt -r requirements-build.txt
py -3.12 build_windows.py --out ..\eznest-build
```

`build_windows.py` makes the portable folder, then runs `ISCC` when Inno Setup 6 is installed. The result is `installer\Output\eznest-setup.exe` and `installer\Output\BUILD.json`. If Inno Setup is missing, the portable folder is still there and `ISCC installer\eznest.iss /DSourceDir=..\eznest-build\dist\eznest` finishes the setup program. This Linux checkout cannot compile that exe.

On the shop server:

1. Close any older eznest, including a 0.12 build on port 8765. Double-click `Stop EZ Nest.cmd`, or use Help → Quit eznest.
2. Run `eznest-setup.exe`.
3. It installs to `C:\Program Files\eznest` and adds a desktop shortcut named eznest.
4. Leave "Start eznest when Windows starts" on if this PC should come up ready. That registers a Task Scheduler task named `eznest`. The task runs as the local user `eznest-svc`, which the installer creates with no administrator rights, and the task uses limited rights. At boot it runs `eznest-server.cmd`, which is `eznest.exe --web --no-browser` with its data in `%ProgramData%\eznest`. The desktop shortcut opens the browser. Boot does not.
5. `eznest-svc` can read and write `%ProgramData%\eznest`. When "This PC runs ONYX" is checked, the installer also grants that account write on `C:\ONYX\EPSON SureColor S80600 ONYX Input`. A hot folder on another PC is a share, and this installer cannot change that share's permissions. On the ONYX PC, allow the sending account to write to the share, or check "This PC runs ONYX" and run eznest on that PC so the folder is local. The account password is random. It is not written into the eznest folder. Task Scheduler keeps it so the task can start at boot. The account can read Program Files the same way other standard users can.
6. Leave "Shop network" off unless other PCs on this network will open the page. Leave "This PC runs ONYX" off unless this is the ONYX computer. Leave "Disable updates (offline install)" unchecked unless this PC must not call GitHub. When that task is checked, eznest does not check for a release and does not read an update token. The gear has the same switch, "Check for updates".

Settings and the hot-folder path for an installed copy live in `%ProgramData%\eznest`, because Program Files is not writable. A portable folder that is not under Program Files still uses `data\` beside the exe.

Closing the browser does not stop eznest. Double-click `Stop EZ Nest.cmd` in the install folder, or use Help → Quit eznest from the full workspace.

## Open from other PCs

Shop network is off until you turn it on. There is no login on the page. Anyone on the shop LAN can Send to ONYX. Do not share this network with guest WiFi.

1. In the installer, check Shop network, or after install open the gear on the server and check Shop network. Restart eznest so the new binding is the one that is running.
2. The gear shows the address, `http://<server-name>:8765/web`, and the first private address. Other shop PCs open that address. They do not install eznest.
3. The installer opens Windows Firewall for TCP 8765 on the private profile only when Shop network is selected. It does not open a public profile.
4. The warning in the gear stays visible while Shop network is on: anyone on the shop LAN can Send to ONYX. Do not share this network with guest WiFi. Do not forward port 8765 to the internet.

A container still uses `--host 0.0.0.0` without shop-network mode. That accepts loopback host names on the published port and rejects every other name.

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

The simple page is one screen: drop files and they nest together. Each file keeps its own quantity. Change the material, the width, or a quantity and it nests again, then Send to ONYX. While it nests, the page shows progress and Stop · keep best. A PDF-compatible `.ai` file imports as PDF. If it cannot be read, the page says Save as PDF. Material, width, hot-folder path, and cut names stay between sessions.
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

Open http://127.0.0.1:8765/web. By default the server accepts only loopback host names, including whatever port Docker publishes. Shop network is separate: the gear or the installer can listen on this computer and accept its name. That option is off unless you turn it on, and it is for the shop LAN.
Publish port 8765, or the page will refuse the request.

Send to ONYX writes one frozen package. Sending again, or opening the page again after a
restart, returns that same file and the same SHA-256. The layout id and hash stay in that
package. The page shows material used, waste, and sheets.

The gear holds the shop handoff. Width, next to the material and the sets, is the
nest width in inches. It starts at the material's printable width and can be
lowered. Nesting uses that width minus the mark margins. A width above the
material, a width that cannot hold the widest piece, or a blank width is one red
sentence and Send stays off. Sheets still split at 60 in unless you change it.
A mark margin, 0.4 in by default, is reserved around the sheet so ONYX CutServer
can add registration marks and barcodes. The gear says it must match the CutServer
mark setup. Those marks are not drawn unless Draw registration marks is on.
Cut spots default to CutContour_Thru-cut and CutContour_Kiss-cut. LNThru-cut and
LNKiss-cut are the alternate preset. A cut name that is not thru or kiss blocks
Send and names that layer or spot. The sheet ID is on screen and printed in the
file margin. Send to ONYX confirms the material, width, length, pieces, and sheet
ID before it writes the pack. Full-bleed artwork is offset 1/16 in past the cut
(or 1/8 in) without moving the cut paths. The hot-folder path is labeled EPSON
SureColor S80600 ONYX Input, or the pack downloads when that path is empty. An
optional staging folder is off until you turn it on. On the ONYX PC the suggested
path is `C:\ONYX\EPSON SureColor S80600 ONYX Input`. On every other PC it is
`\\ONYX\EPSON SureColor S80600 ONYX Input`. The gear shows that default and does
not connect it until you set the path. The page does not build OXF files,
manifests for the cutter, or cut recipes.

Not in v1: job history, order intake, AI batching, cost tracking, an ONYX or GoProduce proof, and laminate cost.
The nest, the file import, and the saved shop settings stay separate so those can be added later.
PDF import is still 20 MB, 25 pages, named spots or layers, and no DeviceN, non-PDF AI, or EPS.
SVG and PDF cannot share a batch. One batch holds 800 pieces. See [supported files](docs/PRODUCTION-FILES.md).

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

GitHub Actions runs the checks on Windows, Python 3.12 and Node 24. The Windows installer workflow, on a `v*` tag or a manual run, builds `eznest-setup.exe` with Python 3.12 and Inno Setup 6.7.3. A local build still uses a directory outside the source tree.

## Repository map

| Files | Purpose |
| --- | --- |
| production.html, queue.css, queue-app.js, production-features.js | Interface and production controls |
| queue-core.js, svg-io.js | Identity, quantities, units, presets and SVG |
| pdf_io.py | Piece ownership, cut detection, previews and original-object PDF output |
| cut_mapping.py, cut-mapping.js | Shareable cut rules, names and validation |
| engine.py, nesting.py, sheets.py | Nesting, validation, filler and sheets |
| production.py, costing.py | Packages, sorting and material estimates |
| server.py, launcher.py, shop_deploy.py | Local API, shop network, and release check |
| installer/ | Inno Setup script for the shop server |
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
