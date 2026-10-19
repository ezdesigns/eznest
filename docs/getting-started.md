# Getting started for testers

Ez Nest **0.12.0-beta.1** is a local Windows app. It nests PDF, PDF-compatible AI, and SVG on this computer. It does not need an account, and it does not send jobs to a website. The browser page is only a window onto the app at `http://127.0.0.1:8765/`.

This build is for the EZ Designs print line to try beside the current MX workflow. It is not a signed installer, and the original-code license is still an open decision for Ezven.

## Download the Windows build

Use the portable ZIP from GitHub Actions. **Code → Download ZIP is source code**, not the app.

1. Open [the Windows portable workflow](https://github.com/ezdesigns/eznest/actions/workflows/windows-portable.yml).
2. Open the latest **successful** run on `main`. Until this tester work is on `main`, use the run on the tester pull request instead.
3. Download the artifact named `eznest-windows-x64`.
4. Unzip that download. Inside it is `eznest-<version>-windows-x64.zip`, a `.sha256` file, and `manifest-beta.json`.
5. Unzip `eznest-<version>-windows-x64.zip` all the way. You should see a folder named `eznest` containing `eznest.exe` and `_internal`.

Keep `_internal` beside `eznest.exe`. Do not pull single files out of the folder. The app is not code-signed, so Windows SmartScreen may say it is unrecognized. Ezven has not chosen a certificate yet. You can still run it with Windows' **More info → Run anyway** if you trust this download.

Optional check: the `.sha256` file is the checksum of the portable ZIP. What's new uses that same kind of check when it installs a later build. See [updates.md](updates.md).

## Run it

1. If an older Ez Nest is open, use **Help → Quit eznest**, or run `Stop EZ Nest.cmd` from the old folder. Two copies cannot share port 8765.
2. Double-click `eznest.exe`.
3. The browser opens `http://127.0.0.1:8765/`. Use the same browser next time. The queue is stored there.
4. Closing the browser does **not** stop the app. **Help → Quit eznest** does.

`START HERE.txt` in the same folder is the short version of these steps.

## Import artwork

Drop files on the page, or use **Add files**.

| File | What Ez Nest needs |
| --- | --- |
| PDF | Closed cut strokes it can map, and a closed outer boundary for each piece. |
| AI | The same, and the file must have been saved with **Create PDF Compatible File**. Native AI that is not PDF is rejected. |
| SVG | Grouped pieces with a clipping outline, a cut contour, or a path named `EZN_BOUNDARY`. |

PDF/AI and SVG cannot be in the same batch. Watched folders still pick up SVG only. Use **Add files** for PDF and AI.

For PDF and AI:

1. At import, name the generic cut spot if the file uses one. The starter name is `CutContour`.
2. If a generic cut has no thru/kiss type, choose thru-cut, kiss-cut, or "assign in the RIP".
3. Enter bleed that is **already in the file**, in millimeters. `0` clips at the cut. Ez Nest does not create missing bleed.
4. Review every detected piece, its cut counts, and its size before nesting.

Thru-cut and kiss-cut paths stay with their piece. A piece inside another piece is not inferred. Split those in the source file first.

## Nest

1. Set the usable roll width. Length is calculated.
2. Set complete-set quantities.
3. Optional: customer, order, and kit under the job options. Per-sheet length and material price are under **Settings**.
4. Click **Nest selected jobs**.
5. Review the preview. Layout details can download a comparison worksheet for the MX test. Sorting IDs are on the map, not on the print art.

One material and up to 100 pieces per batch. The layout is a search, not a guaranteed best nest.

## Send the file to ONYX

Ez Nest does not drive the printer or the cutter. It writes a package the RIP can open.

1. Open **Output profile** and choose **ONYX / GoProduce**, or the shop profile you were given.
2. Leave colors on **Preserve source colors**. Set the printer ICC and color conversion in ONYX, not here.
3. Leave registration marks to ONYX or GoProduce. Ez Nest removes recognized old marks so the RIP can make new ones.
4. Confirm the cut names ONYX is set to read. This build writes separate spots and layers. The starter output names are `CutContour_Thru-cut` / layer `Thru-cut` and `CutContour_Kiss-cut` / layer `Kiss-cut`. Source files may use `LNThru-cut` and `LNKiss-cut`; those names are recognized on the way in. They are starter aliases, not proof that ONYX is mapped to them. If ONYX rejects the cut, note the name it showed and report it.
5. Export. PDF/AI jobs export PDF. SVG jobs export SVG.
6. If **Settings → Source & save folders** has a save folder, the package is written there. Otherwise the browser downloads a ZIP.
7. In ONYX, open the **print PDF** (not the sorting map). Let ONYX add marks and send the cut on to GoProduce.

**Exported** means the package was saved. It does not mean the job printed or cut.

The bleed required by the ONYX profile may still need to be confirmed. An unmet profile requirement is called out on the page. You can save a working package, but the jobs stay in the queue.

## What's new, updates, and problems

- **What's new** shows this changelog and whether a newer build is published.
- **Update now** installs that build after a checksum check and a restart. **Install on next restart** waits until the next time you open Ez Nest. Jobs in this browser and files in `data\` stay. If the new build does not start, the previous build is put back. Details: [updates.md](updates.md).
- **Report a problem** (also under Help and What's new) opens a GitHub issue with the version filled in. You need access to the private `ezdesigns/eznest` repository. Do not attach customer artwork unless Ezven asks.

## Known limits

- One material, up to 100 pieces. PDF import is limited to 20 MB and 25 pages.
- No EPS, no DeviceN cut colors, no automatic bleed, no color conversion, no inventory, and no direct printer or cutter control.
- Hidden or conditional PDF layers, annotations, and ambiguous contours are rejected.
- Source clipping is not redaction. Use print-only art.
- This beta has not been proven on the shop's ONYX, GoProduce, and cutter path. That is the point of the test in [testing-plan.md](testing-plan.md).
- Code signing and the license for Ez Nest's own code are not decided. Dependencies keep their own licenses under `licenses\`.

## If it will not open

- Port 8765 is already in use: quit the older Ez Nest, then start this one again.
- Windows blocked the unsigned exe: **More info → Run anyway**, or ask Ezven before you bypass the warning on a machine you do not trust.
- The page is blank: the app is still starting, or the browser opened before it was ready. Refresh `http://127.0.0.1:8765/`. If it never loads, quit and start `eznest.exe` again.
