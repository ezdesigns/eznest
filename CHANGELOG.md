# Changelog

## 1.0.0-rc.2

Ez Ink's shop answers for the ONYX handoff.

- Cut spots default to CutContour_Thru-cut and CutContour_Kiss-cut. LNThru-cut and LNKiss-cut stay as the alternate preset.
- A cut path whose name is not thru or kiss blocks Send. The red sentence names that layer or spot, and THRU / KISS assigns it.
- Mark margin defaults to 0.4 in, labeled so it matches the CutServer mark setup. Max sheet length defaults to 60 in. White gloss stays 54 in stock, 51.5 in printable, Quick Set Substance Gloss GL [EZ Designs 80600] @ 720-CT.
- Material presets are buttons. The last material and width are remembered.
- Material used, waste, and sheets stay on screen. Send to ONYX asks once, with the material, width, length, pieces, and sheet ID, then Confirm send or Back.
- Staging folder is optional and off until it is turned on.
- The sheet ID is on screen and printed as small text in the file margin. No barcode.

## 1.0.0-rc.1

Shop release candidate. v1 is nesting only: drop artwork, nest it, and send the sheet to ONYX.

- Gang sheet. Drop several files at once, or add more after the first. Each file has its own quantity. They nest together on one sheet. The page lists each file with its quantity and a remove button.
- PDF-compatible Illustrator `.ai` files use the PDF importer. A file that cannot be read shows one red sentence: Save as PDF.
- A batch holds 800 pieces, so a normal day's run of small stickers fits. The page shows nest progress and Stop · keep best.
- `eznest-web.bat` starts the local server and opens the shop page. No terminal is required.
- Material, nest width, hot-folder path, and cut spot names persist in the browser for this address. The hot-folder path also stays on this computer.
- The shop handoff from the beta stays: mark margins, LN cut names, printable width, auto bleed, and the ONYX hot folder.
- One shop server, many browsers. `eznest-setup.exe` installs to Program Files, adds a desktop shortcut, and can start eznest at boot with Task Scheduler. The shop PC does not need Python or Git.
- Shop network is off by default. Turn it on to listen for other PCs at `http://<server-name>:8765/web`. The gear shows that address and warns that it is for the shop network only.
- The hot-folder default is `C:\ONYX\EPSON SureColor S80600 ONYX Input` on the ONYX PC and `\\ONYX\EPSON SureColor S80600 ONYX Input` from every other PC.
- The gear shows the version. Update checks the latest eznest release and downloads the official installer.
- GitHub Actions builds `eznest-setup.exe` on Windows. A `v*` tag attaches it to the release. A manual run uploads it as an artifact.

Not in v1, so they can be added later without replacing the nest: job history, order intake, AI batching, cost tracking as a product, OXF or cut recipes, and a physical ONYX proof.
