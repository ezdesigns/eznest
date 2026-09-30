# Windows beta validation — 2026-09-29

Version: 0.10.0-beta.1. Built on Windows 11 x64 with Python 3.12.14 and PyInstaller 6.22.3. The distributed app is an unsigned portable directory, not an installer.

## Automated checks

- 41 Python tests passed: geometry, quantities, spacing, fixed width/automatic length, filler rollback, source folders, safe output, frozen batches, output profiles, launcher and shutdown.
- Node queue, shop-profile contract and seven Illustrator boundary-policy checks passed; queue-app.js syntax passed.
- No missing required runtime DLL was reported during packaging. PyInstaller warnings concern optional/platform-specific imports and dynamically exposed NumPy/Shapely attributes; the actual packaged engine was exercised below.

## Executable checks

The candidate zip was extracted to a Windows path containing spaces and launched with its bundled executable on isolated port 8766. No source Python was used to run the server or nesting worker. Testing on a separate clean Windows installation remains outstanding.

1. Empty first-run screen loaded with roll-width input, file picker and example action.
2. Imported the packaged four-piece SVG through the file picker; set two complete sets and 200 mm roll width. Invalid width 0 was rejected and the valid prior width restored.
3. Native worker placed all eight pieces. Automatic used length was 145.7063751220703 mm; width stayed exactly 200 mm. Independent geometry validation passed.
4. Export SVG downloaded a six-file zip. The downloaded bytes matched the server's frozen archive. artwork.svg contained eight transformed artwork groups at 200 mm physical width, with no sorting-ID overlay. The CSV contained eight piece rows and the manifest reported eight pieces.
5. Saved jobs left the active queue. Reload preserved export history, width and the saved preview. Add to queue restored the source job with its quantity.
6. Changing display units to inches preserved the physical 200 mm width. The optional roll-length limit remained Automatic.
7. Mixed example: six required pieces plus one optional sticker fit on the same 200 mm roll, using 104.601692199707 mm of length. Direct destination export wrote all six files under a new batch folder. Source files were retained.
8. A second executable launch reused the same version and exited successfully. The source PowerShell launcher also recognized and reused that server.
9. Help > Quit eznest shut down the service. Restart restored the frozen mixed-job result and both history entries. Final static cleanup stopped background folder polling on quit.
10. Development-only SVG test pages returned 404 in the portable build. Browser warning/error logs were empty during the functional flow. The updated main preview restored its prior saved batch and ONYX profile without changing its queue.

The final package uses the tested executable and runtime. Updated static resources (poll shutdown cleanup and empty-count styling) were synchronized to the extracted test folder, reloaded and checked before packaging. Operator docs and this validation report were added afterward; no engine code changed.

## Limits of this release

These checks use synthetic, printable SVG artwork. They do not establish superiority over MX or certify ONYX/GoProduce production output. Native AI/PDF artwork, PDF/EPS export, CMYK conversion, bleed generation and named cut-spot output remain unsupported. One material per batch, up to 100 pieces; heuristic layout, not a guaranteed global optimum. No jobs were sent to a printer or cutter.
