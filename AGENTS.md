# Instructions for AI agents

These instructions apply throughout this repository. Read [GOALS.md](GOALS.md)
first, then [CONTRIBUTING.md](CONTRIBUTING.md) and the current task/PR description.
Keep this guide aligned with verified behavior; do not mark planned features as done.

For onboarding or a real-file Illustrator pilot on a separate design PC, follow
[START-CODEX.md](START-CODEX.md). It contains the operator handoff prompt, isolated
source setup, test-folder workflow and local report requirements. Do not treat
that pilot as authorization to change the protected shop installation.

## Product direction

Ez Nest helps print-shop employees prepare and nest jobs quickly without needing
the owner to operate the tool. Keep the main workflow simple: select/import a
job, choose material and quantity, review a large preview, then send the frozen
output to the RIP hot folder. Show material used, waste, sheets and piece counts.
Keep advanced configuration out of the everyday workflow. Preserve physical
scale, artwork, cut paths and explicit production review before sending.

The long-term OUTPUT value is understanding shop demand and available capacity.
Build useful local nesting first, then explicitly opted-in machine/capacity
sharing. Local job observations do not prove printer utilization, free capacity,
or completed printing. Do not turn this into an order-management system or RIP.

## Branch and release boundaries

The owner promoted the tested integration head `27f48d2` to `main` on 2026-10-26.
The interface cleanup is isolated on `feature/clean-job-settings-20261027` for
a draft PR to that main baseline. This is not permission to merge future PRs or
deploy the shop PC; the protected PR #1 / rc.4 gate below is unchanged.

- Current readiness work belongs on draft PR #4, branch
  `cursor/shop-open-handoff-9891`, targeting `cursor/eznest-web-mvp-8f6a` (PR #1).
- External contributors follow `CONTRIBUTOR-CODEX.md`: create a separate branch
  from `cursor/shop-open-handoff-9891` and submit a draft PR back to that branch.
  They must not push directly to the integration branch or target PR #1's base.
  This does not retarget the owner's existing draft PR #4.
- Protect PR #1 and rc.4 at `2c1f547a2449f600711ccb21ddf235f9b9114f00`.
  Do not modify that branch or replace its shop-test installation before the
  ONYX white-gloss test passes and v1 merges. Automated tests do not satisfy
  that physical production gate. Verify its status rather than assuming it passed.
- Do not merge, publish a release, push a release tag, change repository
  visibility, or bump the version as part of readiness/pilot work. These require
  a separate explicit user instruction. Passing the shop gate alone is not
  permission to publish. Keep the PR draft unless instructed otherwise.
- Inspect the latest remote head and local changes before editing or pushing.
  Preserve other editors' work. Reconcile concurrent changes; never overwrite
  them with a force push. Use an expected-head check when updating through APIs.
- After v1 merges, verify the new target with the task context and update this
  guide. Do not silently retarget while the current gate is still active.

## Invariants

- Bind to `127.0.0.1` by default. LAN requires explicit `--lan`; saved preferences
  must never widen the listener. Preserve existing Host/origin/session checks.
- The Windows boot task uses limited `eznest-svc`, not administrator or SYSTEM.
- OUTPUT defaults off. Its current placeholder switch sends nothing and is not
  consent for future transfers. Never add silent uploads or send customer artwork.
- Keep credentials, certificates, customer files, generated packs, local databases
  and `.local/` out of commits. Use synthetic fixtures. Inspect the final diff.
- Preserve checksum validation, rollback safeguards and shop settings. Program
  Files updates use the separate, explicitly approved helper in
  `installer/update-shop.ps1`, valid matching publisher signatures and the existing
  limited service task. Unsigned builds keep the manual-install guard. Do not
  remove signature or idle-work gates to make an update appear successful.
  Real signed install/rollback validation remains required before rollout; see
  [Windows updates](docs/windows-updates.md).
- `version.json` is the sole version source. Retain LICENSE, NOTICE,
  THIRD_PARTY.md and dependency licenses. Implement original code; competitor
  demonstrations are workflow references, not source code to copy.

## Illustrator and materials

Read [illustrator/START HERE.txt](illustrator/START%20HERE.txt) before changing
the pilot. Use exact layer names `print`, `thru-cut`, and `kiss cut`; canonical
cut spots are `CutContour_Thru-cut` and `CutContour_Kiss-cut`.

Work on a separate production copy and never silently save over the source.
The operator chooses an existing Adobe PDF preset. Regular is the only configured
Illustrator preparation material. Chrome and Holographic need actual shop rules
before enabling specialty preparation. The browser may save named roll presets
for already prepared artwork; these contain nesting dimensions and spacing only. Do not invent color substitutions, bleed values or PDF presets.
`Nest in eznest.jsx` remembers those choices per Windows user; `EZ Nest Settings.jsx`
changes them. Revalidate saved presets against Illustrator's available presets,
never silently substitute. New exports start at one set. Auto-load only an empty
workspace after shop setup; preserve existing reviewed/sent work on page reload.
The bridge is loopback-only and needs eznest on the same PC as Illustrator.

The pilot does not yet generate bleed, repair clipping groups, register templates,
automatically recolor production art, or return the nest to Illustrator. Preserve
those limitations in the UI/docs until implemented and validated. Keep
`bridge-core.js` beside the JSX and compatible with ExtendScript's ES3 runtime.

The simple shop page preserves prepared PDF artwork automatically. `artwork_bounds.py`
builds conservative paint envelopes for nesting and spacing; original PDF drawing
objects and cut paths remain at their original scale. Connected paint stays
grouped. Separate pieces may overlap only in blank source clearance before
nesting: each export guard must exclude every other protected paint core, and
each separated unit needs its own cuts. Preserve the full export guard; reducing
it can change edge pixels. Nesting envelopes still include that guard and spacing.
Unowned paint rejects instead of disappearing. Do not reintroduce an
operator-entered bleed amount or automatic enlargement in this flow. Legacy simple
page jobs require re-import from the original, not a previously clipped export.

Open dashed cut strokes require an explicit possible-guide review in the simple
page. Show their positions against the other cut outlines; exclude only the exact
reviewed IDs after confirmation bound to the file hash and cut mapping. Never
automatically interpret all dashed lines as guides or export them as solid cuts.
Closed, filled or clipped dashed cuts remain unsupported. Cancelled/failed imports
must leave the previous job usable, and a multi-file selection is all-or-nothing.

Large direct PDF uploads first make a temporary print copy without Illustrator
private editing data; original files remain untouched. Unnamed closed strokes
require a file-bound operator review and an explicit kiss/through choice. Never
infer cuts from a filename or magenta alone. Transparent image borders may be
excluded from nesting space only when the original supported soft mask proves
zero alpha; retain all nonzero alpha, interpolation allowance and export guards.
The automatic-section and continuous order cap is 5000 pieces; each solver input
stays at 800 or fewer. Continuous print joins the order on one checked PDF page,
up to 5000 mm or known available stock, whichever is shorter. Validate all pieces
together, including spacing across internal search sections. Repeated rectangular
envelopes compare allowed row orientations without trimming protected artwork.
Thumbnail detail is bounded for large orders; print and cut export
must retain original source objects and commands. Optional filler jobs are not
supported with a required order above 800 pieces.

The separate portable trial is packaged with `build_shop_trial.py` after a
`build_windows.py --portable-only` build. Its `--shop-test` launch creates marked
local trial data and TEST Output, disables update checks and refuses other running
servers. Preserve those isolation guards and the original shop installation.
`Prepare and Nest.jsx` aliases the existing preparation flow; do not claim it
adds automatic recoloring, bleed or a native editable Illustrator return path.

## Local tracking

`workload.py` records prepared packs, successful hot-folder deliveries and explicit
removals. Store opaque IDs, UTC times, counts and measurements, not customer names,
filenames, paths or artwork. Preserve deduplication, 90-day pruning on writes,
restart persistence and failure isolation: a tracking error must not fail delivery.

A browser download is not hot-folder delivery. Removal is not proof of cancelled
printing. Recalculating the same Illustrator handoff/settings counts once; a fresh
Illustrator export is a new attempt. Handoff PDFs are separate local artwork
storage, not workload telemetry; do not upload them or claim they follow the
workload database's retention policy.

## Where to work

| Area | Main files |
| --- | --- |
| Employee interface | `web.html`, `web.css`, `web.js` |
| Local API and lifecycle | `server.py`, `launcher.py` |
| Nesting and independent geometry checks | `engine.py`, `nesting.py`, `sheets.py` |
| PDF/cuts and frozen output | `pdf_io.py`, `cut_mapping.py`, `cut-mapping.js`, `production.py`, `output_folder.py` |
| Illustrator handoff | `illustrator/`, `illustrator_bridge.py` |
| Local activity | `workload.py` |
| Windows packaging and updates | `build_windows.py`, `installer/`, `shop_deploy.py`, `installer_update.py` |

Treat `archive/` as historical reference. Check the active route and callers
before editing older interfaces. Keep Python/JavaScript contracts consistent.

## Windows validation

Use 64-bit Python 3.12, Node 24 and PowerShell 7. Browser tests require installed
Chrome or Edge and the Playwright Python package. There is no npm install.
Run from the repository root in a development checkout, with test output folders.

```powershell
py -3.12 -m venv .local/venv
.local/venv/Scripts/python.exe -m pip install -r requirements.txt
.local/venv/Scripts/python.exe -m pip install playwright
.local/venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
node --check queue-app.js
node --check production-features.js
node --check cut-mapping.js
node --check web.js
node tests/test_queue.cjs
node tests/test_shop_profiles.cjs
node tests/test_cut_mapping.cjs
node tests/test_production_features.cjs
node tests/test_boundaries.cjs
node tests/test_illustrator_bridge.cjs
pwsh -NoProfile -File tests/test_shop_scripts.ps1
pwsh -NoProfile -File tests/test_update_helper.ps1
```

Use `.github/workflows/test.yml` as the current CI command list. Run focused
regressions while developing, then the full Windows checks for runtime changes.
For documentation-only changes, check links, commands and the diff; do not claim
older test results ran against the new commit. Add tests for meaningful behavior,
not tests that merely duplicate implementation details. Inspect desktop/mobile
screenshots after UI changes. Check the installer workflow for packaging changes.

The local PowerShell tests mock system changes; they do not validate a real
elevated install or rollback. `tests/test_installed_shop.ps1` performs real fresh
install/startup/uninstall checks ONLY on disposable GitHub-hosted Windows runners;
never bypass its environment/clean-machine guards to run it on a shop or developer
PC. It does not validate signed upgrades or rollback. Illustrator, ONYX and cutter tests belong on an isolated
test PC/VM or the explicitly authorized shop-test setup. Never use the live hot
folder for automated tests. If a dependency or host is unavailable, report exactly
what was tested and what remains unverified.

`tests/test_installed_tester.ps1` and `tests/installed_tester_smoke.py` separately
exercise the per-user tester installer on disposable GitHub-hosted runners. Never
bypass their hosted-runner guards on a local PC. Reusable browser checks may run
against a separately launched isolated synthetic test server, but that proves
only the app flow, not installation. Report standard-user, native Save As and
physical print/cut acceptance separately from runner automation.

## Completion report

Explain the operator-visible change, relevant test results, remaining limitations,
and draft commit/PR. Keep unchecked readiness items open until evidence supports
completion. Distinguish local tests, current-commit CI, installer artifacts, and
physical production validation. Do not claim that building an installer publishes
a release or that sending to a folder confirms printing.
