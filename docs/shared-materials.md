# Shared shop materials: internal pilot

One EZ Nest host stores `materials.sqlite3` alongside its other local data.
Browsers connected to that same host share the saved material list and stock.
Independent installations have independent inventory. This does not enable LAN
access or create separate job workspaces: the current host still has one active
nesting workspace. Take turns operating jobs during this pilot.

## Operator flow

1. Edit a material, enter measured stock on the roll, then **Save material**.
   The stock field includes stock already reserved for pending jobs. Leave it
   blank if unknown; an unknown stock level cannot be reserved. Existing browser
   presets are not silently imported or overwritten; explicitly save each one.
2. Nest and review the pieces. **Edit material → Reserve for this job** holds its roll length. Nesting and saving a file alone do not reserve
   or deduct stock. A layout created before saving its shared material needs to
   be nested again to bind it to that material record.
3. In the same material editor, expand **Reserved jobs & usage**. After using the
   material, choose **Confirm material used** on its reservation.
   Stock is deducted once. Alternatively, **Release reservation** frees unused
   stock. Used stock cannot be returned by releasing a reservation.
4. Measure and correct stock in Edit material after replenishing a roll or
   accounting for setup/feed waste. The reservation covers the layout length,
   not extra printer feed or unreported waste. Use separate material names for
   separate rolls when those rolls must be tracked independently.

On-roll stock, reserved length and available length are distinct. Low-stock
warnings use available stock. Connected visible pages refresh approximately
every ten seconds, and stock checks at reservation time are authoritative.

Reservations remain listed when starting another job or restarting the app.
Release an old reservation explicitly if a replacement layout supersedes it;
the app cannot infer whether a previously saved file will still be printed.

## Integrity and privacy

Material edits use an expected revision. Concurrent reservations are serialized
in SQLite transactions and cannot overbook known stock. Repeating a reservation
or its usage confirmation is safe. Layout IDs and result fingerprints bind a
reservation to the reviewed result; lengths come from server results rather
than a number supplied by a browser. Existing Host, origin and session checks
apply to every write.

The database stores material settings, stock, opaque layout references, lengths,
states and UTC timestamps. It does not store customer filenames or artwork and
does not transmit anything to OUTPUT. Back it up with the host data directory
while the app is stopped. Inventory is a separate file; older builds ignore it
and must not be used for stock tracking after reverting.

This is manual operator-confirmed usage, not printer completion detection or
automatic purchasing. There are no employee roles or cross-host sync. Do not
present this as safe simultaneous job editing; independent workspaces require
separate work before a multi-designer rollout.
