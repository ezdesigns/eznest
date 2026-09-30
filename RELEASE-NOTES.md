# eznest 0.12.0-beta.1 — Mixed-cut beta

- One piece now owns print artwork, its outer boundary and every interior cut.
- Separate thru-cut, kiss-cut and generic operations survive rotation, copies and sheets.
- Shareable exact/prefix input rules and per-operation output spot/layer names.
- Review per-piece cut counts; unresolved generic cuts require an explicit import choice.
- Reject conflicting names, duplicate cuts and paths without a unique piece owner.
- Remove recognized old registration paint so the RIP can create new sheet marks.
- Operation counts and output names in the export manifest, CSV and sorting guide.

Active PDF/AI jobs imported before 0.12 must be re-added and reviewed. Old frozen
packages and source files are untouched. Preserve app data and browser storage.

PDF-compatible AI only; SVG remains a separate workflow. No DeviceN cut colors,
EPS, color conversion, automatic bleed, inventory or direct printer/cutter control.
Supported ownership is geometric containment, not arbitrary Illustrator grouping.
Unknown marks embedded in print artwork cannot be removed automatically.
Actual shop ONYX/GoProduce validation and an equal-settings MX comparison remain open.

Extract the full unsigned Windows package and keep _internal beside eznest.exe.
See docs/PRODUCTION-FILES.md for supported structures and limits.
