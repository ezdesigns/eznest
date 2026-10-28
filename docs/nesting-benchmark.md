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
noise. The solver budget is the `seconds` field on each case. The seed is
passed through. Two Sparrow workers are not bit-identical across processes;
see the repeat notes below.

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

`tools/fixtures/nest_bench_baseline.json` is the engine on `main` at
`8a35416`, before these packing changes and before pull requests #11 and #12
merged. The "main now" column is one later run of `main` at `445fd6e` (after
#11's guarded solver) with the same cases, measured so the settle pass can be
compared with the solver that is already on `main`. It is not a second
committed baseline. The final column is one full run of this branch after the
merge. Every case validated: no overlap, the operator gap held, margins held.

Mean length treats every case equally. The three 1000-piece rows are most of
the summed length, so the equal-weight mean moves less than the sticker cases.
Read the rows. Length change is final versus the recorded baseline.

| | Baseline | Main now | Final | Versus baseline |
| --- | ---: | ---: | ---: | ---: |
| Cases valid | 23/23 | 23/23 | 23/23 | |
| Mean roll length | 796.02 mm | 794.33 mm | 783.89 mm | −1.52% |
| Mean utilization | 62.01% | 62.23% | 64.23% | +3.58% relative |
| Sum of case lengths | 18308.55 mm | 18269.57 mm | 18029.44 mm | −279.11 mm |
| Sum of wasted area | 1,079,525 mm² | 1,072,508 mm² | 1,032,046 mm² | |

Versus `main` at `445fd6e`, that run was −1.31% mean length. After pull
request #13 merged (`1be77ad`), the same cases were run again: mean length
784.17 mm versus that `main` at 794.72 mm (−1.33%). 22 cases were shorter.
`concave_locked_seed42` was 350.71 mm on `main` and 351.65 mm here (+0.27%,
inside the 0.3% band). None regressed. Minimum gap was 3.000 mm on every case.

| Case | Pieces | Seed | Baseline mm | Main now mm | Final mm | Versus baseline | Final util |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sticker_sheet_quarters_seed42 | 16 | 42 | 100.80 | 100.80 | 91.00 | −9.72% | 61.27% |
| sticker_sheet_quarters_seed7 | 16 | 7 | 100.82 | 100.82 | 91.00 | −9.74% | 61.27% |
| sticker_sheet_locked_seed42 | 16 | 42 | 116.06 | 116.06 | 91.00 | −21.60% | 61.27% |
| sticker_pages_quarters_seed42 | 12 | 42 | 92.01 | 92.01 | 91.00 | −1.10% | 55.15% |
| mixed_demo_quarters_seed42 | 12 | 42 | 213.36 | 213.36 | 209.39 | −1.86% | 67.67% |
| mixed_demo_quarters_seed99 | 12 | 99 | 214.22 | 214.22 | 210.22 | −1.87% | 67.40% |
| mixed_demo_locked_seed42 | 12 | 42 | 231.47 | 231.47 | 227.03 | −1.92% | 62.41% |
| pieces60_quarters_seed42 | 60 | 42 | 418.41 | 418.62 | 411.86 | −1.57% | 68.74% |
| pieces60_quarters_seed7 | 60 | 7 | 420.44 | 421.48 | 418.00 | −0.58% | 67.73% |
| pieces60_locked_seed42 | 60 | 42 | 443.42 | 442.98 | 436.75 | −1.50% | 64.82% |
| pieces180_quarters_seed42 | 180 | 42 | 1259.81 | 1244.24 | 1235.63 | −1.92% | 68.74% |
| pieces180_quarters_seed3 | 180 | 3 | 1253.66 | 1253.03 | 1236.18 | −1.39% | 68.71% |
| pieces180_locked_seed42 | 180 | 42 | 1382.94 | 1382.25 | 1368.11 | −1.07% | 62.08% |
| continuous_1000_quarters_seed42 | 1000 | 42 | 3409.50 | 3409.50 | 3382.01 | −0.81% | 70.96% |
| continuous_1000_locked_seed42 | 1000 | 42 | 3550.74 | 3550.74 | 3514.01 | −1.03% | 68.30% |
| continuous_1000_free_seed42 | 1000 | 42 | 3409.50 | 3409.50 | 3382.01 | −0.81% | 70.96% |
| concave_quarters_seed42 | 27 | 42 | 323.30 | 322.99 | 315.91 | −2.29% | 62.99% |
| concave_quarters_seed11 | 27 | 11 | 327.43 | 318.03 | 318.09 | −2.85% | 62.56% |
| concave_free_seed42 | 27 | 42 | 334.74 | 321.89 | 316.27 | −5.52% | 62.92% |
| concave_locked_seed42 | 27 | 42 | 355.06 | 354.73 | 344.23 | −3.05% | 57.80% |
| workshop_quarters_seed42 | 6 | 42 | 110.56 | 110.56 | 106.90 | −3.31% | 64.44% |
| workshop_quarters_seed1 | 6 | 1 | 110.56 | 110.56 | 106.86 | −3.35% | 64.46% |
| workshop_locked_seed42 | 6 | 42 | 129.74 | 129.74 | 126.00 | −2.89% | 54.67% |

The seed is passed into Sparrow. Two search workers are not bit-identical
across processes. Before #11 merged, repeats of the kept engine put
`pieces180_quarters_seed42` at 1229.33, 1231.36 and 1237.75 mm, and
`concave_locked_seed42` at 344.23, 346.58 and 348.94 mm. All of those were
still shorter than the baseline. The final column above is one later run on
the merged solver, not a seed picked after the fact. One worker was more
stable and was dropped because two cases grew past the baseline (see the log).

The settle pass stops when two real outlines would be closer than the operator
gap. This run reports a minimum gap of 3.000 mm on every case. `validate_result`
still allows 0.001 mm of slack; the settle pass does not spend it.

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
| 8 | Re-measure steps 1–3 on `main` after #11 | kept | #11's guarded solver, measured alone, moved the mean from 796.02 mm to 794.33 mm (−0.21%). The same settle and shelf pass on that solver then reached 783.89 mm. Versus that `main` run: 22 shorter, `concave_quarters_seed11` +0.02% (inside the noise band), 0 regressions. Shelf rows now refuse an orientation whose buffered outline does not fit the usable width, matching the solver guard. Compaction stops at the full operator gap. |
| 9 | Let a measured sheet length match the piece extent | kept | Settling puts a piece on the margin, so the sheet length equals that piece's extent. Subtracting the margins missed by about 10⁻¹⁴ mm and `validate_job` rejected the sheet. The shop page then stayed blocked, and tests waited out their 90 s timeout. The fit check now allows the same 0.001 mm already used by the geometry check. Nest lengths are unchanged. |

Free rotation on the concave set is not automatically better than quarter turns at this budget. On the original baseline it was longer (334.74 mm versus 323.30 mm). After #11 and the settle pass it is 316.27 mm versus 315.91 mm for quarter turns, still not shorter.

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
- Pull request #11 merged onto `main` while this loop was running. The
  recorded baseline file is still the pre-#11 engine. The "main now" column
  is one run of `445fd6e` and was not committed, because replacing the
  baseline would hide the original measurement.
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
