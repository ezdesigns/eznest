# Changelog

## 1.0.0-rc.1

Shop release candidate. v1 is nesting only: drop artwork, nest it, and send the sheet to ONYX.

- Gang sheet. Drop several files at once, or add more after the first. Each file has its own quantity. They nest together on one sheet. The page lists each file with its quantity and a remove button.
- PDF-compatible Illustrator `.ai` files use the PDF importer. A file that cannot be read shows one red sentence: Save as PDF.
- A batch holds 800 pieces, so a normal day's run of small stickers fits. The page shows nest progress and Stop · keep best.
- `eznest-web.bat` starts the local server and opens the shop page. No terminal is required.
- Material, nest width, hot-folder path, and cut spot names persist in the browser for this address. The hot-folder path also stays on this computer.
- The shop handoff from the beta stays: mark margins, LN cut names, printable width, auto bleed, and the ONYX hot folder.

Not in v1, so they can be added later without replacing the nest: job history, order intake, AI batching, cost tracking as a product, OXF or cut recipes, and a physical ONYX proof.
