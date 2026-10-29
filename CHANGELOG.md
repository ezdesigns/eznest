# Changelog

## Unreleased

- The shop computer must connect to OUTPUT before nesting, sending, or stock
  changes. The first run is a Connect screen. Designer PCs are told to ask
  the shop computer. A paired host keeps working for 14 days when OUTPUT is
  unreachable, with a banner after 3 days. Activity sharing stays opt-in.
  `EZ_NEST_DEV_NO_OUTPUT=1` applies only to a source checkout in dev mode.
- Public preparation: internal agent notes, the tester kit, and the shop-specific
  preset are removed. The example shop preset uses placeholder printer and
  hot-folder paths. OUTPUT's service origin is `EZ_NEST_OUTPUT_URL` or
  `outputUrl` in `shop.json`, defaulting to https://output.jeezlabs.io.
  Activity sharing stays opt-in and off. The OUTPUT account connection is
  required on official builds. Background update checks default off
  (`EZ_NEST_UPDATES` defaults to `0`, and `shop.json` `updates` defaults to
  false). Turn them on from Settings and that environment variable. Downloads
  still require a matching SHA-256, and installation stays a separate click.
  The application license is Apache-2.0.
- Backend telemetry draft records nested layouts, frozen packs, planned material,
  local saves and configured print-folder handoffs. Local APIs accept explicit
  queue/print confirmations and current roll readings. A banded atom outbox and
  fake-hub sample prepare the future connector; OUTPUT transmission stays off.
  The shared hub contract and dashboard connection are not yet integrated.
- Stream browser PDF/AI uploads directly to disk, up to 2 GB, without base64 expansion. Illustrator/legacy JSON handoffs allow 256 MB; SVG remains 8 MB. Parser and geometry limits still apply.

- The job panel has Upload job, Choose material, and Where will you print?
  In-house stays selected and uses the existing effort choices. Don't print is
  the other choice, a light green button with a green Still get paid badge. The
  note title is "Don't print it. Let another shop do it." Join the waitlist
  opens the OUTPUT waitlist. Learn more opens the OUTPUT site. Nothing is sent
  or saved from that note.
- The host settings can connect to OUTPUT with a pairing code. The credential
  stays on this computer. Launch settings still take precedence. Sharing still
  requires the on-screen agreement. Disconnect removes the saved credential.
- Settings opens in a centered dialog. Specialized cut and print-software options
  are collapsed and explained in plain language. Field labels show help on hover,
  focus or tap. Clicking outside the material editor cancels unsaved edits.
- The upload area has a simple upload icon. Nest stays visible and disabled until
  a job is ready. Per-file quantities replace the extra Copies dropdown; widths
  are edited with the material. Bottom help sections and the diagram are removed.

First run, checked updates, and a shop that is not hard-wired to one hot folder.

- The first time the page opens, it asks for the hot folder, the printer, the cut spot names, and the units. Use Example shop preset fills placeholder values. Nothing is connected until you save.
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

Shop-server install audit.

- The boot task runs as the local user `eznest-svc` with limited rights. That account is not an administrator. It can read and write `%ProgramData%\eznest`, and on the ONYX PC it can write the local hot folder.
- Shop network stays off until it is turned on. There is no login. The gear and the install notes say anyone on the shop LAN can Send to ONYX, and this network must not be shared with guest WiFi.
- Update checks can be turned off. While they are off, eznest does not call GitHub and does not read an update token.
- `BUILD.json` next to `eznest-setup.exe` records the version, the commit SHA, and the SHA-256 of that exe. The same file is in the Actions artifact.

## 1.0.0-rc.2

Shop answers for the RIP hot-folder handoff.

- Cut spots default to CutContour_Thru-cut and CutContour_Kiss-cut. LNThru-cut and LNKiss-cut stay as the alternate preset.
- A cut path whose name is not thru or kiss blocks Send. The red sentence names that layer or spot, and THRU / KISS assigns it.
- Mark margin defaults to 0.4 in, labeled so it matches a cutter mark setup. Max sheet length defaults to 60 in. The sample white-gloss roll stays 54 in stock and 51.5 in printable, with a placeholder quick-set name.
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
- The hot-folder default follows the example shop preset: a local folder when this PC holds the hot folder, and a share path from every other PC.
- The gear shows the version. Update checks the latest eznest release and downloads the official installer.
- GitHub Actions builds `eznest-setup.exe` on Windows. A `v*` tag attaches it to the release. A manual run uploads it as an artifact.

Not in v1, so they can be added later without replacing the nest: job history, order intake, AI batching, cost tracking as a product, OXF or cut recipes, and a physical ONYX proof.
