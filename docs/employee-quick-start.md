# Ez Nest for designers

Ez Nest nests a print job and writes the finished file to the shop hot folder.
It runs on one host PC. You use a browser.

## Open the page

Nothing to install on a designer PC. Open the address your admin gave you:

`http://SHOP-HOST:8765/web`

`SHOP-HOST` is the host computer's name. Keep that PC awake during the day.

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

Nothing leaves the shop unless the owner turns on OUTPUT sharing on the host.
Your artwork stays on that computer.

## For the admin

Designer PCs only open `http://SHOP-HOST:8765/web`. Install Ez Nest on the
host. Shop network has to be on or other PCs cannot open the page. See
[Security](../SECURITY.md).

**Unsigned installer.** Windows SmartScreen warns on an unsigned
`eznest-setup.exe`. Choose **More info**, then **Run anyway**. Leave
SmartScreen on for the rest of the PC.

**Firewall.** If Windows asks whether to allow eznest through the firewall,
allow private networks only. When **Shop network** is checked, setup adds an
inbound rule named `eznest` for TCP port 8765 on the Private profile only.
Leave the Public profile closed, and leave port 8765 off the internet.

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
