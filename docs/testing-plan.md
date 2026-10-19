# Compare Ez Nest with the current MX workflow

Use real EZ jobs that would have gone through MX. The goal is to see whether this beta saves material, costs time, or makes errors before anyone switches a live queue over. A shorter nest on synthetic art is not that result.

Ez Nest does not run MX. Layout details → **Download comparison worksheet** records the Ez Nest side and leaves the MX fields empty for the operator to fill in. Keep that JSON with the notes below.

Do this on a shop PC with the [portable build](getting-started.md), ONYX, and the usual MX seat. Same person can run both, one job at a time, so the clock is the operator, not two people talking.

## Same job, both tools

For each job:

1. Start from the same print-ready file MX would have used. Do not clean it up in a way you would not do for MX.
2. Write down the file name, customer/order if you already use one, material, usable width, quantity, and whether the piece has thru-cut, kiss-cut, or both.
3. Nest it in MX the way you do today. Record the length MX used, how long the nesting took you (including fixing the file), and any error MX showed.
4. Nest the same file in Ez Nest at the same usable width and the same complete-set quantity. Enter only bleed that is already in the art. Record the length Ez Nest shows, the piece count, and the engine time from the comparison worksheet.
5. Export the Ez Nest PDF and open the **print PDF** in ONYX. Do not send it to the cutter until the file at least opens and the cut names look right, unless Ezven has asked for a physical cut on that job.
6. If you print or cut it, record whether the size matched, whether the cut landed on the art, and whether every piece in the kit was present.

Keep PDF/AI jobs out of SVG batches. If Ez Nest rejects the file, that rejection is a result. Save the exact sentence and [report it](getting-started.md#whats-new-updates-and-problems). Do not keep retrying with a different file and drop the failure.

## What to compare

**Material.** Area is usable width times length used. Compare those lengths only when the width, quantity, and piece count match. Material saved is MX area minus Ez Nest area. A negative number means Ez Nest used more. Do not compare a job Ez Nest split across sheets with an MX nest that used a different sheet limit unless you write both limits down.

**Time.** Operator minutes from "I have the file" until the nest is accepted or abandoned. That includes import errors and rework. The worksheet's engine seconds are only the search, not the person's time. Record both.

**Errors.** Count each of these when it happens, including jobs you then fixed and finished:

- Import rejected, or the wrong pieces detected
- Wrong cut type (thru marked as kiss, or the reverse)
- Piece missing, duplicated, or the wrong size on the preview
- ONYX or GoProduce rejected the file, or mapped the cut to the wrong tool
- Reprint or recut
- Update installed and had to roll back, if you were testing updates the same day

A job that finishes in both tools with no reprint is zero errors for that row, even if one nest is longer.

## What this does not decide

A handful of jobs will not prove Ez Nest is better than MX. It tells Ezven where this beta disagrees with the shop. Heuristic nests can waste space on awkward shapes. Physical registration still has to be checked on the machine before a result is treated as production-ready.

Code signing and the license are not part of this test.

## Results template

Copy this block once per job. Leave a cell blank rather than guessing. Attach the comparison worksheet JSON when you have it.

```text
Job:
Date:
Operator:
Ez Nest version:
Source file (name only, no customer art):
Material and usable width:
Quantity (complete sets):
Cuts (thru / kiss / both / none):

MX length:
Ez Nest length:
MX area (width × length):
Ez Nest area:
Material saved (MX area − Ez Nest area):

MX operator minutes:
Ez Nest operator minutes:
Ez Nest engine seconds (from the worksheet):

Piece count MX:
Piece count Ez Nest:
ONYX opened the Ez Nest PDF (yes/no):
Cut names ONYX showed:
Printed or cut (yes/no):
Size correct (yes/no/not checked):
Cut aligned (yes/no/not checked):
Kit complete (yes/no/not checked):

Errors (list, or "none"):
Notes:
```

## Roll-up

After the batch of jobs, add one summary:

```text
Jobs compared:
Jobs Ez Nest rejected:
Jobs ONYX rejected:
Jobs with a reprint or recut:
Total MX area:
Total Ez Nest area:
Net material saved:
Total MX operator minutes:
Total Ez Nest operator minutes:
Jobs where Ez Nest was slower to operate:
Follow-ups for Ezven:
```

File the summary as a GitHub **Tester note** if you have repository access, or send it to Ezven with the worksheets. Leave customer files out of the repository.
