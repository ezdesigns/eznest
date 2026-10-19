# Getting started for testers

eznest **1.0.0-rc.1** is the shop page: drop artwork, nest it, and send the sheet to ONYX. It runs on one Windows PC. Other shop PCs open that page in a browser. It does not need an account, and it does not send jobs to a website.

This build is for the EZ Designs print line to try beside the current MX workflow. It is not a signed installer, and the license for eznest's own code is still an open decision for Ezven.

## Download the installer

Use `eznest-setup.exe` from GitHub Actions. **Code → Download ZIP is source code**, not the app.

1. Open [the Windows installer workflow](https://github.com/ezdesigns/eznest/actions/workflows/windows-installer.yml).
2. Open the latest **successful** run. Until this work is on the default branch, use the run on the tester pull request.
3. Download the artifact named `eznest-setup`.
4. Unzip that download. Inside it is `eznest-setup.exe`, `eznest-setup.exe.sha256`, and `manifest.json`.

The `.sha256` file is the checksum of the installer. Update uses that same check before it installs a later build. The manifest in this artifact is unpublished, so the app will not install it by itself. See [updates.md](updates.md).

The installer is not code-signed. Windows SmartScreen may say it is unrecognized. Ezven has not chosen a certificate yet. You can still run it with **More info → Run anyway** if you trust this download.

## Install and run

1. If an older eznest is open, including a 0.12 build, quit it. Two copies cannot share port 8765. `Stop EZ Nest.cmd` in the old folder does that.
2. Run `eznest-setup.exe`. It needs an administrator once.
3. It installs to `C:\Program Files\eznest` and adds a desktop shortcut. Leave **Start eznest when Windows starts** on if this PC should come up ready.
4. Leave **Shop network** off unless other PCs on this network will open the page. Leave **This PC runs ONYX** off unless this is the ONYX computer.
5. The shortcut opens `http://127.0.0.1:8765/web`. Use the same browser next time. Material, width, and cut names for this address stay in that browser. The hot-folder path also stays on this computer, in `C:\ProgramData\eznest`.
6. Closing the browser does not stop eznest. `Stop EZ Nest.cmd` in the install folder does.

## Drop, nest, send

Drop PDF, PDF-compatible AI, or SVG on the page. Several files in one drop nest together. Each file has its own quantity.

| File | What eznest needs |
| --- | --- |
| PDF | Closed cut strokes it can map, and a closed outer boundary for each piece. |
| AI | The same, and the file must have been saved with **Create PDF Compatible File**. If it cannot be read, the page says Save as PDF. |
| SVG | Grouped pieces with a clipping outline, a cut contour, or a path named `EZN_BOUNDARY`. |

PDF/AI and SVG cannot be in the same batch.

1. If a plain CutContour has no thru/kiss type, choose Thru or Kiss when the page asks.
2. Set the usable width. Length is calculated. A batch holds 800 pieces.
3. **Send to ONYX** writes the pack to the hot folder. If no hot folder is set, the browser downloads a ZIP instead.

## ONYX hot folder

Open the gear.

- On the ONYX PC, check **This PC runs ONYX**. The default folder is `C:\ONYX\EPSON SureColor S80600 ONYX Input`.
- On every other PC the default is `\\ONYX\EPSON SureColor S80600 ONYX Input`.
- Paste another path if the shop folder is different. That path is what Update keeps.

Leave colors as they are in the file. Set the printer ICC and registration marks in ONYX. This page removes recognized old marks so the RIP can make new ones. The starter cut names are `LNThru-cut` and `LNKiss-cut`. If ONYX rejects a cut, note the name it showed and report it.

**Sent** means the pack was written. It does not mean the job printed or cut.

## What's new and problems

- **What's new**, in the gear, lists this build.
- **Update** checks for a newer approved release. Details are in [updates.md](updates.md).
- **Report a problem** opens a GitHub issue with the version filled in. You need access to the private `ezdesigns/eznest` repository. Do not attach customer artwork unless Ezven asks.

## Known limits

- One material, up to 800 pieces. PDF import is limited to 20 MB and 25 pages.
- No EPS, no DeviceN cut colors, no inventory, and no direct printer or cutter control.
- Hidden or conditional PDF layers, annotations, and ambiguous contours are rejected.
- A piece inside another piece is not inferred. Split those in the source file first.
- The page can offset full-bleed artwork past the cut. It does not certify ink coverage.
- Job history, order intake, and cost tracking are not on this page.
- This build has not been proven on the shop's ONYX, GoProduce, and cutter path. That is the point of [testing-plan.md](testing-plan.md).
- Code signing and the license for eznest's own code are not decided.

## If it will not open

- Port 8765 is already in use: quit the older eznest, then start this one again.
- Windows blocked the unsigned installer: **More info → Run anyway**, or ask Ezven before you bypass the warning on a machine you do not trust.
- The page is blank: refresh `http://127.0.0.1:8765/web`. If it never loads, run `Stop EZ Nest.cmd` and start the desktop shortcut again.
