# Changelog

## Unreleased

- Backend telemetry draft records nested layouts, frozen packs, planned material,
  local saves and configured print-folder handoffs. Local APIs accept explicit
  queue/print confirmations and current roll readings. A banded atom outbox and
  fake-hub sample prepare the future connector; OUTPUT transmission stays off.
  The shared hub contract and dashboard connection are not yet integrated.
- Stream browser PDF/AI uploads directly to disk, up to 2 GB, without base64 expansion. Illustrator/legacy JSON handoffs allow 256 MB; SVG remains 8 MB. Parser and geometry limits still apply.

- The job panel has Upload job, Choose material, and Where will you print?
  In-house stays selected and uses the existing effort choices. Another shop
  shows "What's this?" and opens a short note on every job. OUTPUT passes the
  nested job to a shop that has the material, the machine and the time. The
  shop keeps the customer and the sale. There is no stock check, no early-pilot
  line, and no earnings claim. Join the waitlist and Learn more open the OUTPUT
  site. Nothing is sent or saved.
- Settings opens in a centered dialog. Specialized cut and print-software options
  are collapsed and explained in plain language. Field labels show help on hover,
  focus or tap. Clicking outside the material editor cancels unsaved edits.
- The upload area has a simple upload icon. Nest stays visible and disabled until
  a job is ready. Per-file quantities replace the extra Copies dropdown; widths
  are edited with the material. Bottom help sections and the diagram are removed.

First run, checked updates, and a shop that is not hard-wired to one hot folder.

- The first time the page opens, it asks for the hot folder, the printer, the cut spot names, and the units. Use EZ Designs preset fills today's EZ Designs values. Nothing is connected until you save.
- Send says when the hot folder or share cannot be reached.
- Update checks the SHA-256 sidecar, stages the installer, and rolls back if the new build does not start. What's new, Report a problem, and Update are in the gear. Pre-releases show up when Test channel is on.
- Join OUTPUT network is off. It sends nothing.
- The release address, the token, and the problem-report link can be set without rebuilding. A public repository needs no token.

## 1.0.0-rc.5

Older files that use a plain CutContour name can be sent as kiss or thru.

- A file whose cut layer is exactly CutContour asks once: Plain CutContour found: Kiss or Thru? Kiss is already selected. Confirm renames that layer in the locked file to the kiss or thru name in the gear, including the LN preset.
- Any other unmapped cut name still blocks Send and shows that name.

## 1.0.0-rc.4

Uninstall removes the shop service account.

- Uninstall stops and deletes the `eznest` startup task, then removes the local user `eznest-svc` and the folder permissions granted to that account. If the account is still signed in, uninstall disables it. Shop files in `%ProgramData%\eznest` stay on disk.
- Opening the shop page no longer waits on a hostname lookup. On Windows that lookup ignores the socket timeout and could sit on DNS until the page looked stuck.
- The problem sentence stays red when Windows high contrast is on. That mode otherwise paints it black.
- The shop page does not count as open until its stylesheet and scripts have loaded. A dropped file is requested again. The server keeps the connection open so the file queued behind the page is not dropped. The computer name lookup cannot sit on DNS.

## 1.0.0-rc.3

Ez Ink's audit of the shop-server install.

- The boot task runs as the local user `eznest-svc` with limited rights. That account is not an administrator. It can read and write `%ProgramData%\eznest`, and on the ONYX PC it can write the local hot folder.
- Shop network stays off until it is turned on. There is no login. The gear and the install notes say anyone on the shop LAN can Send to ONYX, and this network must not be shared with guest WiFi.
- Disable updates is off unless the installer task or the gear turns updates off. While updates are off, eznest does not call GitHub and does not read an update token.
- `BUILD.json` next to `eznest-setup.exe` records the version, the commit SHA, and the SHA-256 of that exe. The same file is in the Actions artifact.

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
