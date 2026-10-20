# Using eznest in the shop

## Open your shop bookmark

Your administrator installs eznest on one host PC. On that PC, open the eznest
shortcut. Other employees use the host's browser address only after the shop
network is explicitly enabled. Keep the host awake during shop hours.

## Prepare, review, send

1. Prepare colors, artwork and cut paths in Illustrator. Keep your original;
   save a PDF or PDF-compatible AI production copy. The Illustrator pilot uses
   `print`, `thru-cut`, and `kiss cut` layers and your shop's Adobe PDF preset.
2. Drop the production file into eznest. Choose the approved material and sets.
   Nesting starts automatically. Do not substitute an untested material preset.
3. Review every piece and cut path in the preview. Check width, piece count,
   sheet count, material used and waste. Use Zoom for small details.
4. Choose **Review and send**, then **Confirm send**. A successful send means
   delivery to the hot folder, not that the job printed. Check it in your RIP.
5. Choose **Next job**. If no hot folder is configured, the app offers a ZIP
   download instead; this does not send the job to the printer.

If a send fails, keep the layout. Ask the administrator to restore hot-folder
access, then send again. Reopening the page restores the frozen pack and shows
whether delivery is incomplete. Undo is available only if enabled and the pack
is still in the folder; it cannot cancel printing already started by the RIP.

Settings and local activity stay on the host. OUTPUT sharing is off and sends
nothing. Do not mistake local job activity for printer utilization or completion.

## Updates

The administrator updates the host once for everyone. During the unsigned pilot,
use only the checked installer supplied by the administrator. Signed builds can
offer **Install when finished** after the separate rollout acceptance test passes.
Finish or explicitly discard the current job before installation. Do not replace
the protected rc.4 shop test until its ONYX test passes and v1 merges.

## From Illustrator

Finish colors and existing bleed, save, select complete artwork and cuts, and run
**File > Scripts > Nest in eznest**. First run remembers your approved Adobe PDF
preset, Regular material, width and existing bleed. Later runs open the production
copy directly in eznest: choose sets, review, send. Use **EZ Nest Settings** to
change saved choices. See [Illustrator setup](../illustrator/START%20HERE.txt).
The bridge needs eznest running on the same PC; it does not connect a browser-only
LAN workstation to the host. An existing job requires explicit replacement.
