# Nesting benchmark

This is the material-use loop for the local nester. It measures the engine that
ships in the shop app. It does not send a job, talk to a printer, or upload
artwork.

## Run

From the repository root, with the Python dependencies in `requirements.txt`:

```bash
python tools/nest_bench.py --out tools/fixtures/nest_bench_baseline.json
python tools/nest_bench.py --out /tmp/nest-new.json
python tools/nest_bench.py --compare tools/fixtures/nest_bench_baseline.json /tmp/nest-new.json
python tools/nest_bench.py --cases workshop_quarters_seed42
python tools/nest_bench.py --list
```

`--compare` prints one row per case and exits non-zero when a case regresses.
A regression is any of:

- roll length more than 0.3% longer
- utilization more than 0.3% lower
- validation failure (overlap, gap, or margin)
- a missing case, or a different piece area

Wall time is printed and is not part of the gate. Moves smaller than 0.3% are
noise. The solver budget is the `seconds` field on each case. The same seed
repeats the same layout.

Regenerate outlines only when a demo shape itself changes:

```bash
python tools/nest_bench.py --write-fixtures
```

That rewrites `tools/fixtures/nest_outlines.json`. Record a new baseline after
doing it. The benchmark JSON stores the fixture hash so a silent shape change
cannot be compared as if it were an engine change.

## What the cases are

| Group | Cases | Job |
| --- | --- | --- |
| Small stickers | `sticker_sheet_*`, `sticker_pages_*` | 24×18 mm rounded stickers from the queue demo, on a 120 mm roll and on a 100×140 mm sheet |
| Mixed demo art | `mixed_demo_*` | Trail outlines from `sample-artwork.svg` and helmet outlines from the `queue-app.js` demo, two of each, 180 mm roll |
| 60 and 180 pieces | `pieces60_*`, `pieces180_*` | Mixed rectangles plus an L and a triangle, 180 mm width, 3 mm gap, 5 mm margin |
| Continuous roll | `continuous_1000_*` | 1000 copies of a 24×18 mm rectangle, one page, quarter-turn, locked, and free rotation |
| Odd / concave | `concave_*` | C-notch, arrow, L, badge, triangle, and small fillers. Quarter-turn, free, and locked |
| Workshop | `workshop_*` | The six parts in `sample.json` |

Seeds are part of the case id. The set is not a single lucky seed.

## Baseline

The committed `tools/fixtures/nest_bench_baseline.json` is the measurement on
`main` before the packing changes in this branch. The table below is filled
from that file. Mean length treats every case equally, including the long
continuous orders, so the continuous rows dominate the mean length and the
shorter jobs dominate a utilization average. Read both.

Baseline table: pending the first recorded run.

## Iteration log

Each idea is one change, then the full benchmark. A change stays only when no
case regresses past the 0.3% noise band, validation stays clean, and length or
utilization improves on at least one case.

| # | Idea | Result | Notes |
| --- | --- | --- | --- |
| 0 | Record the current `main` solver | baseline | No packing change |

## Limits

- These are synthetic outlines and the two demo SVGs. They are not customer
  jobs, not scanned art, and not the shop's ONYX or cutter checks.
- Search time is capped per case (1–5 seconds). A 30 or 90 second shop search
  can still find a shorter layout than this budget. The ranking is for this
  budget, not a claim of the best possible nest.
- Utilization is piece area divided by roll width times used length. It does
  not subtract gripper marks, printed bleed, or RIP margins beyond the case
  margin.
- The continuous 1000-piece rows are repeated rectangles, so they take the
  closed-form row layout. They guard that path. They do not exercise the
  800-piece solver cap; the unit tests do.
- Wall time moves with the machine. Do not compare seconds across computers.
- An improvement here does not mean a printed sheet used less vinyl. Nothing
  in this loop is sent to a hot folder.

## Later: gang jobs when it is time to print

Not built. The next iteration, after this single-job loop is trusted, is to
hold ready jobs and nest them together when someone is about to print.

### Data model

Keep the existing job as the unit of artwork and quantity. Add a local gang
record that references jobs; it does not copy artwork into a second library.

- Job: stable id, material id, roll width, gap, margin, pieces, quantity,
  status (`ready`, `held`, `sent`).
- Material: a shop preset id plus the width it was prepared for. Two presets
  with the same name and different widths stay different materials.
- Gang: id, material id, chosen roll width, ordered list of job ids, the nest
  result, and the seed. A job is in at most one open gang.
- The nest input is the union of the selected jobs' pieces, with ids that
  still say which job they came from. Quantities stay exact in the local
  store. Any later shared payload stays banded and allowlisted, same as the
  telemetry contract.

### Grouping

Group only jobs that share a material id and a roll width. A 54 inch laminate
job does not sit on a 24 inch vinyl roll. If two jobs are the same vinyl but
were prepared at different widths, they stay apart unless every piece of the
wider job fits the narrower printable width and the operator picks that width.
Do not stretch or scale art to force a fit.

Within one group, pack the selected jobs as one order so a small job can use
the scrap of a large one. The score is the total roll length of the gang
versus the sum of the jobs nested alone. Keep the separate nests when the gang
is longer, or when mixing them would break a gap, a margin, or a due job the
operator marked as its own sheet. The 800-piece solver cap and the continuous
5000-piece page cap still apply; a gang that would exceed them stays split
into checked sections instead of one unbounded solve.

### What machine access has to provide

A gang is a proposal until an operator sends it. Local nesting does not know
that a printer is free, loaded, or finished. Machine access, when it exists,
needs an explicit record the operator opted into:

- machine id and the material currently loaded (preset id and width)
- printable width and, if known, the length left on that roll
- whether that machine is the one this gang is allowed to use

The gang may then prefer a machine whose loaded material matches. It must not
infer free capacity from a saved file, a hot-folder copy, or a previous nest.
Sending the gang writes the same frozen PDF the single-job path writes.
Completion is still whatever the shop records later, not the save itself.
