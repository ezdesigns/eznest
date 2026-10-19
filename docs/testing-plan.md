# Compare eznest with the current MX workflow

Use real EZ jobs that would have gone through MX. The goal is to see whether this release candidate saves material, costs time, or makes errors before anyone switches a live queue over. A shorter nest on synthetic art is not that result.

Do this on a shop PC with the [installer](getting-started.md), ONYX, and the usual MX seat. The same person can run both, one job at a time, so the clock is the operator, not two people talking.

The shop page is drop, nest, and send. Record the eznest length from the page (Material used) and the time you spent, including fixing the file.

## Same job, both tools

For each job:

1. Start from the same print-ready file MX would have used. Do not clean it up in a way you would not do for MX.
2. Write down the file name, material, usable width, quantity, and whether the piece has thru-cut, kiss-cut, or both.
3. Nest it in MX the way you do today. Record the length MX used, how long the nesting took you (including fixing the file), and any error MX showed.
4. Drop the same file on the eznest page at the same usable width and the same quantity. Record the length eznest shows and the piece count you can see.
5. Send to the ONYX hot folder and open the print file in ONYX. Do not send it to the cutter until the file at least opens and the cut names look right, unless Ezven has asked for a physical cut on that job.
6. If you print or cut it, record whether the size matched, whether the cut landed on the art, and whether every piece in the kit was present.

Keep PDF/AI jobs out of SVG batches. If eznest rejects the file, that rejection is a result. Save the exact sentence and use **Report a problem**. Do not keep retrying with a different file and drop the failure.

## What to compare

**Material.** Area is usable width times length used. Compare those lengths only when the width, quantity, and piece count match. Material saved is MX area minus eznest area. A negative number means eznest used more. Write down the sheet limit when the two tools split the job differently. The page default is a 96 inch sheet.

**Time.** Operator minutes from "I have the file" until the nest is accepted or abandoned. That includes import errors and rework.

**Errors.** Count each of these when it happens, including jobs you then fixed and finished:

- Import rejected, or the page said Save as PDF
- Wrong cut type (thru marked as kiss, or the reverse)
- Piece missing, duplicated, or the wrong size
- ONYX or GoProduce rejected the file, or mapped the cut to the wrong tool
- Reprint or recut
- Update installed and had to roll back, if you were testing updates the same day

A job that finishes in both tools with no reprint is zero errors for that row, even if one nest is longer.

## What this does not decide

A handful of jobs will not prove eznest is better than MX. It tells Ezven where this build disagrees with the shop. Heuristic nests can waste space on awkward shapes. Physical registration still has to be checked on the machine before a result is treated as production-ready.

Code signing and the license are not part of this test.

## Results template

Copy this block once per job. Leave a cell blank rather than guessing.

```text
Job:
Date:
Operator:
eznest version:
Source file (name only, no customer art):
Material and usable width:
Quantity:
Cuts (thru / kiss / both / none):

MX length:
eznest length:
MX area (width × length):
eznest area:
Material saved (MX area − eznest area):

MX operator minutes:
eznest operator minutes:

Piece count MX:
Piece count eznest:
ONYX opened the eznest file (yes/no):
Cut names ONYX showed:
Hot folder used:
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
Jobs eznest rejected:
Jobs ONYX rejected:
Jobs with a reprint or recut:
Total MX area:
Total eznest area:
Net material saved:
Total MX operator minutes:
Total eznest operator minutes:
Jobs where eznest was slower to operate:
Follow-ups for Ezven:
```

File the summary as a GitHub **Tester note** if you have repository access, or send it to Ezven. Leave customer files out of the repository.
