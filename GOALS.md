# Goals

Ez Nest is a free, open-source, self-updating desktop nesting tool that any print shop can install in minutes. It nests files, adds cut marks, and sends them to the RIP hot folder. It is built first for EZ Designs (Austin). Later, and only if a shop opts in, it is how shops join the OUTPUT print production network.

## Who it is for

A print shop that already has a RIP and a hot folder. The operator drops the day's files, nests them, and sends the sheet. No account is required to do that.

EZ Designs in Austin is the first shop. Its printer, cut spot names, units, and hot folder are a preset a shop can apply on first run. They are not required.

Other shops use the same install. They type their own hot folder, printer, cut names, and units.

## What v1 must do

- Install on one Windows PC in minutes. The other shop computers only open a browser.
- Run on that PC. The page is `http://127.0.0.1:8765/web` unless the shop turns the shop network on.
- Nest PDF, PDF-compatible AI, and SVG. Add cut marks. Send one frozen pack to the RIP hot folder.
- Ask once, the first time it opens, for the hot folder, the printer, the cut spot names, and the units.
- Show a clear error on Send when that hot folder or share is missing or cannot be reached.
- Update from a checked installer. If the new build does not start, put the previous build back. Shop settings and the hot folder stay.
- Let a shop report a problem. Once the repository is public, that works with no token.

## Non-goals

v1 does not replace the RIP. Color, ICC profiles, and the RIP's own registration marks stay in the RIP.

v1 does not take orders, keep a job history, track inventory, price the job as a product, or drive the printer or cutter directly.

v1 does not nest on a website. There is no account and no cloud queue.

v1 does not send customer artwork anywhere. Joining OUTPUT is not part of v1.

## Privacy

Ez Nest is local-first. Nothing leaves the shop unless the shop opts in.

The server listens on `127.0.0.1` by default. Shop network is a separate choice. It listens on this computer only when someone starts eznest with `--lan`, or turns Shop network on and restarts. Do not share that network with guest WiFi. There is no login on the page.

Update checks talk only to the configured GitHub release, and only while updates are on. A token is optional. A public repository does not need one.

Join OUTPUT network is off. The switch sends nothing. If a shop turns it on later, the only things shared would be the machine list and free capacity, and only after that opt-in.

## Roadmap

1. **v1 shop test.** EZ Designs runs the release candidate on the shop PC, beside the current workflow.
2. **Open source.** The repository is public, the license is MIT, and a shop can install, update, and report a problem with no token.
3. **OUTPUT opt-in.** A shop can join the OUTPUT print production network. Only the machine list and free capacity would be shared, and only after the shop opts in.
