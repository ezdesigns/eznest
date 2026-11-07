# Ez Nest for designers

Ez Nest nests a print job and writes the finished file to the shop hot folder.
It runs on one host PC. You use a browser.

## Open the page

Nothing to install on a designer PC. Open the address your admin gave you:

`http://SHOP-HOST:8765/web`

For a named shop, enter your name and the invitation from the host. Each code
works once and expires after 15 minutes; every employee needs a separate code.
Access stays in that browser for up to 30 days unless the host removes it.
Logging out ends access, so ask for a new invitation to return. Older shops
without a shop name still use their existing PIN. `SHOP-HOST` is the host
computer's name. Keep that PC awake during the day.

`materials.sqlite3` stays on the host. Do not copy it, and do not open it from a shared drive.

Everyone opens the same host address to share stock. Opening `localhost` on
your own PC points to a different installation. The Inventory view refreshes
about every ten seconds while visible; editing pauses the refresh. Stock use
requires **Reserve for this job**, then **Confirm material used** after use.
Take turns nesting: the host has one shared active job.

The rolls most recently chosen by anyone in the shop appear first. Roll labels
show both the physical width and the width you can print on. Choosing a roll
does not deduct stock. When you load a new roll, select **Replace roll** and
confirm its full length; pending reservations stay attached and are still held.
Click the shop name to see everyone who has joined. Only the host can invite
people or remove their access.

## Each job

1. In Illustrator, build a PDF with layers named `print`, `thru-cut`, and
   `kiss cut`. The kiss-cut layer name has a space. Keep your original file.
2. Drop that PDF on the Ez Nest page. Pick the material. Wait for the preview.
3. Check the pieces, the width, and the length. Choose **Review and save**.
4. Leave **Save to** on the default print folder and choose **Save**. That
   writes the file to the hot folder.
5. Open ONYX and check that the job is there. A save means the file reached
   the folder. It does not mean the job has printed. If this shop does not use
   ONYX, check the RIP your admin named.

## If the page will not load

The host PC is probably off or asleep. Do not reserve material for the job.
Tell the admin, and refresh the page later.

## If a send fails

Leave the layout on the page. Tell the admin. Do not start the job over unless
they ask you to.

## Updates

The admin updates the host once. You do not install anything. Refresh the
browser after they say the host is back.

## Privacy

Connecting to OUTPUT is optional. If this page says to ask the shop computer
to connect to OUTPUT, choose **Skip** and keep nesting. Tell the person at
that PC if they want this computer paired. They paste a pairing code there.
You do not.

Your artwork, filenames, customer names, and stock stay on the host. Connecting
sends the host computer's name, an installation id, and later the app version.
Activity sharing is a separate choice on the host and stays off until they
turn it on.

## For the admin

Designer PCs only open the host address. Install Ez Nest on the host:

1. On the host, open `http://127.0.0.1:8765/web`.
2. Finish the welcome screen, choose **Create a shop**, and enter its name.
   Existing materials stay in this host's inventory.
3. Start the host with **Shop network** enabled. A configured startup task with
   `--lan` needs a restart after the shop is created. Saving a preference does
   not open the listener; see [shop invitations](shop-invitations.md).
4. Open the shop name → **Invite someone**. Give each employee the displayed
   address and a fresh invitation. Employees only need their browser.
5. Optional and recommended: configure local HTTPS. On plain HTTP, someone who
   can watch the shop network can copy a signed-in browser's session. See
   [Security](../SECURITY.md).
6. Connecting to OUTPUT is optional and separate from local shop membership.

Shop network has to be on or other PCs cannot open the page. Creating a named
shop replaces legacy PIN access with individual invitations; invite the
existing employees again.

**Stock database.** `materials.sqlite3` stays on the host. Only the Ez Nest
program on that PC should open it. Do not put the data folder on a shared
drive, and do not copy the database to a designer PC.

**Unsigned installer.** Windows SmartScreen warns on an unsigned
`eznest-setup.exe`. Choose **More info**, then **Run anyway**. Leave
SmartScreen on for the rest of the PC.

**Firewall.** If Windows asks whether to allow eznest through the firewall,
allow private networks only. When **Shop network** is checked, setup adds an
inbound rule named `eznest` for TCP port 8765 on the Private profile only.
By default that rule accepts the local subnet. To allow only the three
designer PCs, give them static addresses and pass them to setup as
`-LanPeers "10.0.0.11,10.0.0.12,10.0.0.13"`. Leave the Public profile closed,
and leave port 8765 off the internet.

**Data folder.** Setup limits `C:\ProgramData\eznest` to SYSTEM,
Administrators, and the `eznest-svc` account. Other Windows users cannot
replace the shop settings file.

**Uninstall.** Uninstall from Windows Settings, or run the uninstaller in
`C:\Program Files\eznest`. That removes the program, the `eznest` startup
task, the firewall rule, and the `eznest-svc` account (if Windows cannot
remove the account because it is still signed in, the account is disabled).
It also removes that account's folder permissions.

`%ProgramData%\eznest\materials.sqlite3` stays on the host.
`installer/uninstall-shop.ps1` leaves shop files in the data folder on disk,
and `installer/eznest.iss` only runs that script. It has no step that removes
`{commonappdata}\eznest`. Shop settings and the other files in that folder
stay with the stock database. The RIP hot folder and the files in it stay too.
