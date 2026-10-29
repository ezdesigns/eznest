# Shop Connector

The Shop Connector is a small program that runs on a shop computer. It watches
the tools you already use, and after a one-time pairing it can send a short
machine summary to OUTPUT.

It does not nest jobs, it does not change Ez Nest, and it does not replace the
RIP or the cutter software. It is off until you turn a plug-in on.

## What you do

1. Copy `connector/config.example.json` to a config file you keep outside the
   program, and set each path you actually want to read.
2. Leave every plug-in `enabled: false` until the path is right.
3. Pair once: `python -m connector pair YOUR-CODE`
4. Check the result: `python -m connector status`
5. Start watching: `python -m connector run`

Pairing exchanges the code for a shop key and stores that key on this
computer. Copying the code into the config file is not required. The key is
not printed. That one pairing request also sends this computer's name and
installation id. Later event posts do not send them again.

To stop everything: `python -m connector disconnect`

That deletes the shop key and any summaries that have not been accepted yet.
It does not delete the RIP log or the cutter log.

## Try it without sending

```
python -m connector replay --fixtures connector/fixtures/
```

This reads the sample files in that folder and prints the summaries it would
send. The samples are invented. They are not customer jobs. Nothing is sent
unless you add `--send`, and `--send` works only after pairing.

## Plug-ins

Each plug-in has its own switch in the config file.

| Plug-in | What it reads | What a summary means |
| --- | --- | --- |
| eznest | The local Ez Nest telemetry database | A finished nest observation, using the existing OUTPUT field list |
| onyx_joblog | ONYX `JobLog.txt` | A print finished on a printer you named in the config |
| summa_joblog | Summa GoProduce `Joblog.csv` | A finished cut |
| inventory | A JSON view of on-hand quantities | The on-hand quantity changed after the connector started |

An ONYX Thrive JobLog line is quoted fields separated by spaces inside
`{{ ... }}`, not a comma-separated table. The field positions come from shop
samples and still need confirming against one real JobLog line. The file name,
job title, Quick Set, print mode, and raw media profile are not sent. Only
status `1` is a completed print. Status `-1` and `0` are sent as abnormal;
which of those two means aborted is not verified. `widthIn`, `mediaUsedFt`,
and `machineModel` are inferred from the samples, not from ONYX documentation.
A logged across-roll size above 64.5 inches is treated as a rotated job and
the axes are swapped.

An ONYX file can mention several printers. The connector sends a printer only
when its name is listed in that plug-in's `printers` list. An empty list sends
nothing.

The Summa file is semicolon-separated and has no header. The columns, in
order, are: Date, Job name, Start time, End time, Material name, Material
thickness, Number of jobs, Job size X, Job size Y, Copies per job, Copy size
X, Copy size Y. You can still set `columns` if a shop export is rearranged.

The first time a plug-in starts, that moment is its connect time. Lines
already in a log are not sent. Lines that arrive while the computer is not
paired are not kept for later.

## Where the lines come from

A plug-in has one source:

- `file` reads one local path from the config file.
- `mounted` reads one local path too. Use this when another program has already
  copied the log onto this computer, or the log is mounted as a normal file.
- `stdin` reads lines from standard input. EZ Ink's watcher can read a log over
  SSH and pass the new lines here. This program does not open SSH itself.

The connector may run on a different computer from the printer. It still does
not fetch logs itself.

## SECURITY

### What leaves the shop

Only two requests are ever made, both POST. The host is pinned to
`https://output.jeezlabs.io`. A different host is used only when the config
file sets `outputHost` to an `https://` host with no path, user, or query.
An environment variable cannot point delivery somewhere else. Redirects are
not followed.

1. Pairing, once: `POST /api/shop/agent/pair`
   The body is the pairing code, a request id, this computer's name, and the
   connector's installation id when that id is 32 hex characters. Those two
   identity fields are sent once, with the pairing code, and are not repeated
   on later event posts. This matches `output_pairing.py`.
2. Events: `POST /api/shop/telemetry`
   The body is one `shop-connector-event/1` event. The shop key is sent only
   as the `Authorization: Bearer` header.

The event fields are listed in `connector/CONTRACT.md`. In short they are:
when it happened, a material class, thickness, sizes, counts, print status,
banded ink and coverage, and salted hashes that stand in for a job or a
material. Ez Nest rows reuse the existing `eznest-observation/1` fields inside
`nest.completed`.

The reply is checked for "accepted" or "already seen" and then discarded.
The connector does not download events, files, or shop records. There is no
read API. Redirects are not followed. A URL in a reply is not opened.

The shop key is scoped to this pairing. It is stored with the same protection
as Ez Nest (`output-credential.bin`: DPAPI on Windows, mode `0600` elsewhere).
It is not written to the event, the log, or the screen.

### What never leaves

- Job names, titles, and file names
- Customer names, phone numbers, email addresses, and street addresses
- Prices, costs, and order ids
- Raw log lines
- IP addresses
- Quick Set names, print-mode text, and raw media or printer strings
- The local salt used for hashes
- Inventory cost, and any customer or order link on a stock row

A job name or file name is reduced to a salted SHA-256 hash. The salt is
created on this computer and is never sent. OUTPUT cannot turn the hash back
into the name.

Numbers are sent as ranges (bands), not exact values. See the band table in
`CONTRACT.md`.

### How files are read

- The log is opened read-only, and other programs may keep writing it.
  The connector never asks for a write handle and never takes an exclusive lock.
- The connector never moves, renames, or truncates a log.
- It reads to the end of the file and remembers a byte offset. The same line
  is also remembered by a hash so a repeated line is not sent twice.
- A last line with no newline is treated as half-written and is left for the
  next read.
- If the file is busy, or it changes while it is being read, the connector
  copies the bytes into its own data folder, closes the log, and parses the
  copy. The copy is deleted. The log is not.
- The first successful look at a log sets the offset to the end of the file.
  Older lines are not parsed and are not sent.
- Each look reads at most 1 MiB. A line longer than 64 KiB is dropped and
  counted, not parsed. The inventory view is refused when it is larger than
  1 MiB, so a partial read cannot look like a quantity change.
- Paths come from the config file on this computer, or from the fixture folder
  when you run `replay`. They are not taken from a log line, an event, or an
  OUTPUT reply.
- Network paths (`https://`, `ssh://`, and `\\server\share`) are rejected.
- The ONYX reader and the Summa reader open only those two logs, one each.
  A file name written inside a log line is not opened.
- The inventory plug-in opens only its configured view. The Ez Nest plug-in
  opens only `telemetry.sqlite3`, and only in read-only mode. It does not
  create that file.
- `status` does not open the logs.

### Inventory

The view may contain `name` or `material`, `category`, `qty_on_hand`, `unit`,
`reorder_threshold`, and `updated_at`. Cost and any customer or order fields
are ignored even if they are present. A summary is sent only when the on-hand
quantity changes after the first reading. That first reading is remembered
and is not sent.

### Kill switch

`python -m connector disconnect` deletes the shop key and drops unsent
summaries. `EZ_NEST_OUTPUT_UPLOADS=0` also blocks pairing and sending, which
is what `--shop-test` already does for Ez Nest. Turning a plug-in to
`"enabled": false` stops that plug-in on the next run.

## Data on this computer

The connector keeps its own folder (`EZ_NEST_CONNECTOR_DATA`, or
`.local/connector` when you run from a checkout). That folder holds the shop
key, a random per-install salt, the file offsets, and unsent summaries. The
salt is created once and stays in that folder. It is not sent. On Linux and
macOS the folder is private to the user (`0700`) and the database is `0600`.
On Windows inheritance is removed and only the current user can read the
folder and database. It is not the Ez Nest job folder. Raw log lines are not
stored there.

## Still unconfirmed

- The ONYX field positions are from shop samples. Confirm them against one real
  JobLog line before enabling that plug-in. `widthIn`, `mediaUsedFt`, and
  `machineModel` are inferred. The difference between ONYX status `-1` and `0`
  is unverified.
- Summa clocks are sent as UTC. Summa sizes default to millimetres.
- OUTPUT has not yet registered `shop-connector-event/1`. Until it has, a live
  send can be refused. Use the dry run until then.
- A log that is replaced (rotated) is treated as a new connect. Lines written
  into the new file before the next look are not sent.
