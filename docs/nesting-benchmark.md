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

## Baseline and final

`tools/fixtures/nest_bench_baseline.json` is the engine on current `main`
before the packing changes, same cases and seeds. The final column is one full
run after the changes that were kept. Every case validated: no overlap, gap
held to the engine's existing 0.001 mm check, margins held.

Mean length treats every case equally. The three 1000-piece rows are most of
the summed length, so the equal-weight mean moves less than the sticker cases.
Read the rows.

| | Baseline | Final | Change |
| --- | ---: | ---: | ---: |
| Cases valid | 23/23 | 23/23 | |
| Mean roll length | 796.02 mm | 784.76 mm | −1.42% |
| Mean utilization | 62.01% | 64.08% | +3.33% relative |
| Sum of case lengths | 18308.55 mm | 18049.41 mm | −259.13 mm |
| Sum of wasted area | 1,079,525 mm² | 1,035,643 mm² | |

| Case | Pieces | Seed | Baseline mm | Final mm | Length | Baseline util | Final util |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sticker_sheet_quarters_seed42 | 16 | 42 | 100.80 | 91.00 | −9.72% | 55.31% | 61.27% |
| sticker_sheet_quarters_seed7 | 16 | 7 | 100.82 | 91.00 | −9.74% | 55.31% | 61.27% |
| sticker_sheet_locked_seed42 | 16 | 42 | 116.06 | 91.00 | −21.60% | 48.04% | 61.27% |
| sticker_pages_quarters_seed42 | 12 | 42 | 92.01 | 91.00 | −1.10% | 54.54% | 55.15% |
| mixed_demo_quarters_seed42 | 12 | 42 | 213.36 | 209.38 | −1.86% | 66.41% | 67.67% |
| mixed_demo_quarters_seed99 | 12 | 99 | 214.22 | 210.21 | −1.87% | 66.15% | 67.41% |
| mixed_demo_locked_seed42 | 12 | 42 | 231.47 | 227.02 | −1.92% | 61.22% | 62.41% |
| pieces60_quarters_seed42 | 60 | 42 | 418.41 | 411.84 | −1.57% | 67.66% | 68.74% |
| pieces60_quarters_seed7 | 60 | 7 | 420.44 | 415.06 | −1.28% | 67.34% | 68.21% |
| pieces60_locked_seed42 | 60 | 42 | 443.42 | 436.75 | −1.50% | 63.85% | 64.82% |
| pieces180_quarters_seed42 | 180 | 42 | 1259.81 | 1237.75 | −1.75% | 67.42% | 68.62% |
| pieces180_quarters_seed3 | 180 | 3 | 1253.66 | 1236.14 | −1.40% | 67.75% | 68.71% |
| pieces180_locked_seed42 | 180 | 42 | 1382.94 | 1368.08 | −1.07% | 61.42% | 62.08% |
| continuous_1000_quarters_seed42 | 1000 | 42 | 3409.50 | 3381.88 | −0.81% | 70.39% | 70.97% |
| continuous_1000_locked_seed42 | 1000 | 42 | 3550.74 | 3513.84 | −1.04% | 67.59% | 68.30% |
| continuous_1000_free_seed42 | 1000 | 42 | 3409.50 | 3381.88 | −0.81% | 70.39% | 70.97% |
| concave_quarters_seed42 | 27 | 42 | 323.30 | 315.91 | −2.29% | 61.55% | 62.99% |
| concave_quarters_seed11 | 27 | 11 | 327.43 | 320.49 | −2.12% | 60.77% | 62.09% |
| concave_free_seed42 | 27 | 42 | 334.74 | 330.48 | −1.27% | 59.44% | 60.21% |
| concave_locked_seed42 | 27 | 42 | 355.06 | 348.94 | −1.72% | 56.04% | 57.02% |
| workshop_quarters_seed42 | 6 | 42 | 110.56 | 106.90 | −3.31% | 62.31% | 64.44% |
| workshop_quarters_seed1 | 6 | 1 | 110.56 | 106.86 | −3.35% | 62.31% | 64.47% |
| workshop_locked_seed42 | 6 | 42 | 129.74 | 126.00 | −2.89% | 53.10% | 54.67% |

The seed is passed into Sparrow. With two search workers, a repeat of the same
process matched `pieces60_quarters_seed42` at 411.84 mm and
`concave_locked_seed42` at 346.58 mm, while `pieces180_quarters_seed42` moved
from 1229.33 mm to 1231.36 mm (0.16%). Across separate full runs the 180-piece
seed-42 length was seen at 1229.33, 1231.36 and 1237.75 mm, and the locked
concave case at 344.23, 346.58 and 348.94 mm. All of those are still shorter
than the baseline. They are not bit-identical. One worker was more stable and
was dropped because two cases grew past the baseline (see the log).

Settled layouts report a minimum gap of 2.999 mm against a 3 mm gap. That is
the same 0.001 mm allowance `validate_result` already uses. The identical
sticker rows report 3.000 mm.

## Iteration log

A change stays only when the full set has no case more than 0.3% longer, no
utilization drop past that band, and validation stays clean. Probes that
already lost on several solver cases were not given a second full run.

| # | Idea | Result | What happened |
| --- | --- | --- | --- |
| 0 | Record `main` | baseline | 23/23 valid. Mean length 796.02 mm, mean utilization 62.01%. |
| 1 | Slide pieces toward the start of the roll after search, real outlines, operator gap, rotation unchanged | kept | Full set: 20 cases shorter, 3 continuous rows unchanged, 0 regressions. Mean length −0.82%, mean utilization +1.98% relative. Largest sticker move about −3.8%. |
| 2 | Bounding-box shelf rows, used only when shorter than the settled search | kept | Versus step 1: the three 24×18 sticker rolls went to 91.00 mm (−6.2%, and the locked roll −18.7%). Other cases unchanged. 0 regressions. |
| 3 | Settle the continuous row layout onto the operator gap. The row pitch had carried a 0.22 mm guard | kept | The three 1000-piece rows: 3409.50→3381.88 mm (−0.81%) for quarter turns and free rotation, 3550.74→3513.84 mm (−1.04%) locked. About 2 s of settle time on 1000 pieces. Existing continuous unit test still passed. |
| 4 | Two restarts when the budget is 4–14 seconds, splitting that budget | dropped | Probe: pieces60 seed 42 411.84→415.99 mm (+1.0%), pieces180 seed 42 about 1231→1262.86 mm (+2.5%), mixed demo flat to slightly worse. The shorter tries lost more than a second seed gained. |
| 5 | Pass outlines to Sparrow largest-area first | dropped | Probe on mixed, 60, 180, concave and workshop: no move outside the repeat band of the 180-piece case. |
| 6 | Give compression half of a budget of 4 seconds or more (default is 80/20) | dropped | Concave quarters seed 42 315.91→323.74 mm (+2.5%). pieces60 +0.2%. Mixed demo unchanged. |
| 7 | One Sparrow worker so a seed repeats more closely | dropped | Full set mean length still −1.13%, but two regressions: `pieces180_quarters_seed3` 1253.66→1262.34 mm (+0.69%) and `concave_free_seed42` 334.74→341.28 mm (+1.95%). Two workers stayed. |

Free rotation on the concave set is not automatically better than quarter turns at this budget. On the baseline it was longer (334.74 mm versus 323.30 mm), and it stayed longer after settling.

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
- Two Sparrow workers are not bit-identical across processes. See the repeat
  figures above. A later compare within 0.3% on a hard case can be that spread.
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
