# Shop setup walkthrough

This is the setup for one Windows shop. A person who runs the shop can follow the steps. An AI coding agent (Codex, Claude, or Cursor) can follow the same steps. Do not skip a step because it looks obvious.

Words used here:

- **Host PC.** The one computer that runs Ez Nest. It should be the print/cut PC that runs ONYX, or whichever PC stays on. It holds the stock database.
- **Designer PC.** Any other computer in the shop. It only opens a web browser. It does not install Ez Nest.
- **RIP.** The print software that watches a folder and prints what lands there. ONYX is one RIP.
- **Hot folder.** That watched folder. A save in Ez Nest writes a file there. It does not mean the job has printed.
- **Shop PIN.** A new PIN is 8 to 12 digits, or a passphrase of at least 10 characters that includes a letter. The host stores a hash, not the text. A PIN saved before this rule can still sign in. Settings asks the host to replace it.
- **Shop network.** Other PCs on this private network can open the page. It is off until you start Ez Nest with `--lan`, and that start is refused until the PIN is saved.
- **HTTP and HTTPS.** The default page is `http://` on port 8765. Local HTTPS is optional. You turn it on only by starting with both a certificate and a key. Empty values leave HTTP.

This file was checked against the source in this repository. It was not clicked through on a Windows shop PC. Tests that install Ez Nest run on a disposable GitHub-hosted Windows runner, or they mock Windows commands. They do not prove a shop PC.

## 1. What Ez Nest is, and how the shop is laid out

Ez Nest nests a print job and writes the finished file to the hot folder. Designers use a browser.

Use one host PC for the whole shop.

1. Install Ez Nest only on the host.
2. The stock database is `materials.sqlite3` in `C:\ProgramData\eznest` on that host.
3. Designer PCs open `http://HOST:8765/web` in a browser. `HOST` is the host PC's Windows name. `8765` is the port Ez Nest listens on.
4. Every designer PC sees the same stock, because they are all looking at that one host. A second install, or `http://127.0.0.1:8765/web` on a designer PC, is a different computer and a different stock list. `127.0.0.1` always means "this PC," not the host.

`materials.sqlite3` stays on the host's own disk. The Ez Nest process on the host is the only program that should open it. Do not put that file on a network share, a mapped drive, or a designer PC. A SQLite database on a share can be corrupted, and a copy is not the shop's stock.

Do not forward port 8765 to the internet. Do not put the host on guest Wi-Fi.

## 2. Before you start

On the host, check these before you install.

1. **Windows network profile must be Private.** When shop network is turned on, setup adds a firewall rule for TCP port 8765 on the Private profile only. A Public profile does not use that rule, so designer PCs cannot open the page. If Windows asks whether to allow a program, do not allow the Public profile. The installer itself does not show that question. It sets the rule with `profile=private`.
   - UNVERIFIED - confirm on a real PC: the Windows Settings clicks that change a network from Public to Private. This repository does not contain those clicks.
2. **The host should not sleep.** If the host is off or asleep, designer PCs cannot open the page, and stock cannot be reserved. The page does not queue those writes for later.
   - UNVERIFIED - confirm on a real PC: the Windows power-settings clicks that stop sleep. This repository does not contain those clicks.
3. **Write down the host's Windows name and its IPv4 address.** After shop network is running, the host page shows them. Settings → **Printer connection & backup files** shows `http://NAME:8765/web` and one private address. That name is `socket.gethostname()` on the host. Designer PCs must use that name, or an address that belongs to the host. Another PC's name is rejected.
   - UNVERIFIED - confirm on a real PC: how you read the name and address before Ez Nest is running (for example `hostname` and `ipconfig`). Those commands are not in this repository.

Use a placeholder when you write notes for someone else. This walkthrough uses **Example shop** and **EXAMPLE-PC**. Those are not a real shop.

## 3. Install on the host

The host is 64-bit Windows 10 or Windows 11. It does not need Python or Git.

### Download the installer

1. Open the GitHub releases page for this repository: `https://github.com/ezdesigns/eznest/releases`
2. Download two files from a **published** release:
   - `eznest-setup.exe`
   - `eznest-setup.exe.sha256`
3. **Code → Download ZIP** is the source code, not the app. Do not run that ZIP as the installer.

A published release gets those files when someone pushes a `v*` tag. A pull-request build can also upload the same files as a workflow artifact. That artifact is for testing a build, not for a shop, unless the owner told you to use that exact build.

UNVERIFIED - confirm on a real PC: that a published release with `eznest-setup.exe` is on that page for the build this shop should install. Listing releases from this checkout showed a draft and no published release. Do not install a draft unless the owner says that draft is the one.

### Check the SHA-256 before you run it

SHA-256 is a fingerprint of the file. The `.sha256` file published next to the installer holds that fingerprint. The program's own check reads the first word in that file and compares it with the file you downloaded. A mismatch means do not run the file.

Put both files in the same folder. In PowerShell, in that folder:

```powershell
$expected = (Get-Content -Raw -LiteralPath .\eznest-setup.exe.sha256).Split()[0].ToLower()
$actual = (Get-FileHash -LiteralPath .\eznest-setup.exe -Algorithm SHA256).Hash.ToLower()
if ($actual -eq $expected) { 'Match' } else { 'Do not run this file' }
```

`Get-FileHash -Algorithm SHA256` and taking the first word of the `.sha256` file are what the Windows installer workflow uses. The published file looks like `hex-digits`, two spaces, then `eznest-setup.exe`. This comparison was not run on a shop PC from here.

UNVERIFIED - confirm on a real PC: run that comparison on the files you downloaded. Do not run the installer if it does not print `Match`.

### The unsigned-installer warning

During beta, `eznest-setup.exe` is unsigned. The Windows installer workflow in this repository does not sign it. Windows SmartScreen can say it protected your PC. SmartScreen is Windows's warning for a program that has no publisher signature. It is not Ez Nest's own check.

The README says: if that screen appears, choose **More info**, then **Run anyway**. Do that only after the SHA-256 matches. Leave SmartScreen on for the rest of the PC.

UNVERIFIED - confirm on a real PC: that those two button labels are what Windows shows. The install test in this repository uses a silent install (`/VERYSILENT`) and does not click SmartScreen.

### Run the installer

1. Close any older Ez Nest that is still using port 8765. **Stop eznest** in the Start menu, or `Stop EZ Nest.cmd` in the old install folder, does that on this PC.
2. Run `eznest-setup.exe`. It asks for an administrator. It installs to `C:\Program Files\eznest`.
3. On the tasks page, use these checkboxes. The words are the installer script:

   | Checkbox | What the installer script sets | What to do |
   | --- | --- | --- |
   | Desktop shortcut | No `checked` flag | Check it if you want a desktop icon. The Start menu group is created either way. The README says this box starts checked. The script does not mark it `checked` or `checkedonce`. UNVERIFIED - confirm on a real PC which box is already ticked. |
   | Start eznest when Windows starts | `checkedonce` (checked the first time) | Leave it on if this PC should be ready after a reboot. |
   | Shop network (other PCs on this network) | Not checked | Check it when designer PCs will open the page. See the order below. |
   | This PC runs ONYX | Not checked | Check it only when ONYX runs on this host. |
   | Check for app updates (also set EZ_NEST_UPDATES=1) | Not checked | Leave it unchecked. |

4. Finish the wizard.

What that install does, when **Start eznest when Windows starts** is checked:

- It creates a local Windows user named `eznest-svc`. That user is not an administrator. The password is random and is not written into the Ez Nest folder.
- It registers a Task Scheduler task named `eznest`. The task runs at startup as `eznest-svc`, with limited rights (not the highest privileges). This is a scheduled task. It is not a Windows service created under that name.
- The task runs `eznest.exe --web --no-browser --data-dir "C:\ProgramData\eznest"`. If **Shop network** was checked, it also passes `--lan`.
- It removes inherited permissions on `C:\ProgramData\eznest`. SYSTEM and Administrators get full control. `eznest-svc` gets modify. Other Windows users cannot replace `shop.json`.
- If **Shop network** was checked, it adds a firewall rule named `eznest`: inbound TCP 8765, Private profile only, `remoteip=localsubnet`. The wizard does not ask for a list of PCs, so a normal install uses `localsubnet` (this subnet only). The rule is not added when Shop network is left off.

The Start menu **eznest** shortcut, and the desktop shortcut, do **not** pass `--lan`. They open this PC only, at `http://127.0.0.1:8765/web`, unless something is already listening on port 8765. If something is already listening, the shortcut only opens the browser. It does not replace that listener.

A later run of `eznest-setup.exe` on a PC that already has Ez Nest does **not** change the startup task or `shop.json`. Checking Shop network on that second run does nothing to the task. That is what `tests/test_installed_shop.ps1` checks. To change shop network after the first install, an administrator re-runs the setup script. The command is in [Shop network after the PIN exists](#shop-network-after-the-pin-exists).

### First-run setup, then the shop PIN

`--lan` will not keep running until a PIN is saved. The program stops with: `Set a shop PIN on this computer before opening the shop network.`

Do the first start **without** `--lan`, set the PIN, then start the task that has `--lan`.

1. If you checked Shop network, the startup task may exit immediately because the PIN is not saved yet. That exit is the check above. The installer only checks that the task was started, not that the process stayed up.
2. Open Start menu → **eznest**. That shortcut does not pass `--lan`. If port 8765 is free, the page opens on this PC only.
3. Go to `http://127.0.0.1:8765/web`.
4. The first page is titled **Ready to nest**. It asks you to check cut line names. Printer and the hot folder are optional. You can choose a folder later, on each save.
   - **Hot folder.** The RIP folder a save writes to. You may leave it blank.
   - **This PC holds the hot folder.** Check this when the folder is on this computer. The example preset then uses `C:\RIP\Example RIP Input`. Leave it off and the example preset uses `\\RIP\Example RIP Input`.
   - **Printer.** Optional. The example preset uses `Example printer`.
   - **Thru spot** and **Kiss spot.** Required, and they must be different names. The example preset uses `CutContour_Thru-cut` and `CutContour_Kiss-cut`.
   - **Units.** Inches, millimeters, or centimeters.
5. **Use Example shop preset** fills those placeholders. Nothing is connected until you choose **Start nesting**.
6. Choose **Start nesting**.

Then set the PIN. Only the host page can do this. A designer PC is refused.

1. On the host, open **Settings** (the gear).
2. Open **Shop PIN**. The hint says: use 8 to 12 digits, or a passphrase of at least 10 characters with a letter. Designer computers enter it once. Ez Nest stores only a hash.
3. Type that in **New PIN or passphrase**.
4. Choose **Save shop PIN**. The page says `Shop PIN saved on this computer.`
5. If the page title is **Replace the shop PIN**, this computer already has a PIN from before the current rule. Designer computers can keep using the old one until you save a new one here. Save a new PIN that meets the rule.
6. Tell the designers that PIN in person. Do not write it in `shop.json`, in a text file in `C:\ProgramData\eznest`, or in a chat with an agent. The host stores only a salted hash in `shop-pin.json`.

A new PIN that does not meet the rule is refused: `Use 8 to 12 digits, or a passphrase of at least 10 characters with a letter.` Digits only: 8 to 12. A passphrase: 10 to 64 characters, no spaces, and at least one letter. An already saved 6 or 7 digit PIN can still sign in.

Five wrong tries from one address lock that address. The first lock is one minute. Each new lock for that same address waits twice as long, up to 64 minutes. The page says `Too many tries from this computer. Wait and try again.` Other computers are not locked by that address. Fifteen failures since the host last reviewed them, from any addresses, show a banner in Settings and write a log line. Choose **Reviewed** on the host after you have read it. That banner does not lock anyone out.

Changing the PIN signs every designer browser out. A designer browser keeps an HttpOnly, SameSite=Strict cookie. It lasts at most 8 hours, and it ends after 60 minutes with no request. It is bound to that computer's address. On HTTP the cookie is not marked Secure. On HTTPS it is. The designer does not receive the host write token. Choose **Log out** in the page header when finished.

### Shop network after the PIN exists

The saved `lan` value in `shop.json` does not open the port. Only a process started with `--lan` does, and only after the PIN exists. The Settings checkbox **Shop network** is disabled. It only shows whether this process was started with `--lan`. Saving settings cannot turn the network on. Choosing Shop network in the installer does that only on a fresh install. After that, change it by running `install-shop.ps1` again and restarting.

1. Stop the this-PC-only copy: Start menu → **Stop eznest**, or run `C:\Program Files\eznest\Stop EZ Nest.cmd`. Closing the browser does not stop Ez Nest. Stop the this-PC-only copy first. If it is still holding port 8765, a later `--lan` start sees Ez Nest already running and leaves the old listener in place.
2. If the first install checked **Shop network**, the startup task already has `--lan`. Start that task again, or restart the PC. The task starts at boot.
   - The installer starts it with `Start-ScheduledTask -TaskName 'eznest' -TaskPath '\'` while it is running as administrator.
   - UNVERIFIED - confirm on a real PC: whether a Windows user who is not an administrator can press Start on that task in Task Scheduler. A reboot starts it when **Start eznest when Windows starts** was checked.
3. If the first install left **Shop network** unchecked, running the installer again will not add `--lan`. An administrator runs the setup script after the PIN is saved. `localsubnet` is the right `remoteip` unless you mean to list designer PCs.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\eznest\install-shop.ps1" -DataDir "C:\ProgramData\eznest" -App "C:\Program Files\eznest\eznest.exe" -OnyxPc 1 -Lan 1 -StartAtBoot 1 -Updates 0 -LanPeers "localsubnet"
```

Use `-OnyxPc 0` when this host does not run ONYX. Use `-LanPeers` with a comma-separated list of the designer PCs' IPv4 addresses when the rule should not cover the whole subnet. The script accepts `localsubnet` or 1 to 16 IPv4 addresses. The addresses below are documentation placeholders, not a shop:

```powershell
-LanPeers "192.0.2.11,192.0.2.12"
```

Give those PCs static DHCP leases if you list them. The firewall rule's `remoteip` is then that list instead of `localsubnet`. The profile stays Private. Public is not opened.

4. On the host, open Settings → **Printer connection & backup files**. When shop network is running, the page shows `http://NAME:8765/web`. That string is built as `http://` in the program. Designer PCs use that address while you stay on HTTP.

### Optional local HTTPS

HTTP is the default. On HTTP, anyone who can watch the shop LAN can copy a signed-in browser's session cookie and reuse it until it expires or the designer chooses **Log out**.

Local HTTPS is the recommended extra step. Leave it off until the owner asks for it. You must pass both a certificate and a key. Leaving both empty keeps HTTP. The setup script refuses one without the other.

`SECURITY.md` shows how to create the files. Use the host's real Windows name in place of `EXAMPLE-PC`:

```text
openssl req -x509 -newkey rsa:2048 -keyout eznest-key.pem -out eznest-cert.pem -days 825 -nodes -subj /CN=EXAMPLE-PC
```

On Windows, restrict the key before the shop task reads it. `eznest` is a scheduled task running as `eznest-svc`, not a Windows service:

```text
icacls eznest-key.pem /inheritance:r /grant:r *S-1-5-18:(R) *S-1-5-32-544:(R) eznest-svc:(R)
```

Pass both paths together on `install-shop.ps1` as `-TlsCert` and `-TlsKey`, or start with `--tls-cert` and `--tls-key`. Designers then open `https://EXAMPLE-PC:8765/web`. The session cookie is marked Secure. A self-signed certificate is not a public certificate authority. Keep port 8765 off the internet either way.

The address line in Settings is still built as `http://NAME:8765/web`. When HTTPS is on, open `https://` with the same name and port. Do not send designers to the `http://` line for that host.

If you run `install-shop.ps1` yourself in a window and leave both TLS paths empty, the script can ask you to press Enter to keep HTTP, or to type `HTTPS` to stop. The setup wizard launches that script hidden.

UNVERIFIED - confirm on a real PC: whether that hidden wizard run shows the question, and the exact browser buttons for a self-signed certificate warning.

## 4. shop.json

Shop settings for an installed copy live in:

`C:\ProgramData\eznest\shop.json`

That folder is locked down (see the install step). A normal Windows user cannot replace this file. An administrator can. The PIN is not in this file.

Ez Nest reads the file again when the page asks for shop status. Restart anyway after a hand edit. The listen address is chosen only when the process starts. Changing `lan` in the file does not open or close port 8765, and it does not change the startup task's command line. The hot folder the program writes to is also stored in `output-folder.json`. Editing `hotFolder` in `shop.json` does not move that folder until you save the hot folder in the page (first-run **Start nesting**, or Settings → **Save settings**).

After an edit: stop Ez Nest, then start the `eznest` task again (or restart the PC).

Fields:

| Field | Meaning |
| --- | --- |
| `onyxPc` | `true` when this PC holds the hot folder / runs ONYX. `false` otherwise. It picks the example path (`C:\RIP\Example RIP Input` when true, `\\RIP\Example RIP Input` when false). It does not connect the folder by itself. |
| `lan` | `true` when Shop network was selected. This is a saved flag. It does not open the network. The process must be started with `--lan`, and a PIN must already be saved. |
| `updates` | `false` by default. Background update checks also need the process environment `EZ_NEST_UPDATES=1`. Both must be on. The installer checkbox only saves this flag. |
| `outputNetwork` | `false` by default. This is **Join OUTPUT network**. That control is hidden in the page. Turning it on does not open a connection and does not send anything. It is not OUTPUT sharing. Leave it `false`. |
| `printer` | Printer name, up to 80 characters. May be empty. |
| `hotFolder` | Hot-folder path, up to 400 characters. May be empty until first-run setup. |
| `thru` | Thru-cut spot name, up to 80 characters. Required before setup is finished, and it must differ from `kiss`. |
| `kiss` | Kiss-cut spot name, up to 80 characters. Same rule. |
| `units` | `in`, `mm`, or `cm`. Anything else is treated as `in`. |
| `setupComplete` | `false` until **Start nesting** succeeds on the host. Then the Ready to nest panel stays hidden. |

The program also stores `channel` (`stable` or `test`), `outputUrl` (empty means `https://output.jeezlabs.io`), and `sourceRoots` (folders the host has approved). If those keys are missing, the defaults above are used. If they are already in the file, do not delete them. Do not add a PIN, a token, a password, or a `githubToken`. A token in this file is ignored.

Example for a host that runs ONYX, with shop network saved, updates off, and setup not finished. Replace the placeholder path with the shop's own folder. `EXAMPLE-PC` is not a value in this file. It is the host name designers type in the browser.

```json
{
  "onyxPc": true,
  "lan": true,
  "updates": false,
  "channel": "stable",
  "outputNetwork": false,
  "setupComplete": false,
  "printer": "Example printer",
  "units": "in",
  "thru": "CutContour_Thru-cut",
  "kiss": "CutContour_Kiss-cut",
  "hotFolder": "C:\\RIP\\Example RIP Input"
}
```

If the hot folder is a share on the host, the path is a UNC path (a path that starts with `\\`):

```json
"hotFolder": "\\\\EXAMPLE-PC\\Example RIP Input"
```

The built-in example preset uses `\\RIP\Example RIP Input`, not `EXAMPLE-PC`. `EXAMPLE-PC` means "type the host's real Windows name here."

## 5. Designer PC setup

Nothing to install on a designer PC.

1. On the host, shop network must be running (`--lan` and a saved PIN). Read the address in Settings. It looks like `http://EXAMPLE-PC:8765/web`.
2. On the designer PC, open that address in the browser. Do not open `http://127.0.0.1:8765/web` on the designer PC. That is the designer PC, not the host.
3. The page title is **Shop PIN**. The note says: `Enter the shop PIN or passphrase from the computer that runs Ez Nest. You stay signed in on this browser until you log out, stay idle for an hour, or eight hours pass.`
4. Type the PIN and choose **Continue**.
5. When you are finished, choose **Log out** in the page header.
6. If the PIN was never saved, the page says: `Ask the person at the shop computer to set a PIN, then refresh this page.` There is no box to invent a new PIN here.
7. If the saved PIN is from before the current rule, the note says it still works and the shop computer must replace it. You can keep nesting until then.

The designer PC cannot change shop settings, the PIN, the hot folder, or OUTPUT. Those actions are accepted only from `127.0.0.1` on the host. After the PIN, the designer can nest and use the shared stock.

### Hot folder

Set the hot folder on the **host**, during first-run setup or in Settings → **Where files are saved**. The designer page cannot save it.

- When ONYX runs on the host, check **This PC holds the hot folder** and use a local path, such as `C:\RIP\Example RIP Input`.
- When the RIP folder is on another PC, use a UNC path, such as `\\EXAMPLE-PC\Example RIP Input`.

The process that writes the file is Ez Nest on the host, running as `eznest-svc`. That account needs write access to the folder. The installer does not change a share's permissions. It grants `eznest-svc` write on a local hot folder only when `output-folder.json` already has a local path at install time. A UNC path is not granted by that step. If the folder exists but the account cannot write, the page says: `The hot folder exists, but eznest cannot write to it. Ask your shop administrator to give the eznest-svc account access, then save again.` If the folder or share cannot be opened, the page says the hot folder can't be reached, and it does not pretend the job was sent.

A designer does not need that share in order to nest. The host writes the file. If someone on a designer PC also wants to open the ONYX input folder in File Explorer, that folder has to be a Windows share, and this installer does not create it.

UNVERIFIED - confirm on a real PC: that the designer PC can open the share in File Explorer. Share permissions are outside this repository.

## 6. Connect inventory

Stock is typed into the Ez Nest page. This branch has no stock-import command and no `connector/` folder.

On any PC that has the page open (host or designer, after the PIN):

1. In **Choose material**, pick a roll, or choose **+ Add material**.
2. You can also choose **Edit**, or **Material & stock**, to open the same editor.
3. Enter the material name, units, roll width, and printable width.
4. In **Length left on roll**, enter the measured length still on the roll. The hint says to enter the measured length and leave it blank if unknown. The length you type includes stock already reserved for pending jobs. Blank means unknown. Unknown stock cannot be reserved.
5. Choose **Save material**. The page says the material is saved for everyone connected to this shop.
6. Nesting a file, and saving a file, do not subtract stock.
7. To hold stock for a job: nest and review, then in the material editor choose **Reserve for this job**. After the material is used, open **Reserved jobs & usage** and choose **Confirm material used**. **Release reservation** frees a hold you will not print. Used stock is not returned by releasing a reservation.
8. Other open pages on this same host refresh stock about every 10 seconds. If the host is asleep or stopped, the page says shop stock is unavailable. Reconnect before you reserve or confirm.

The database file is `C:\ProgramData\eznest\materials.sqlite3` on the host. Do not copy it. Do not put it on a network share. Browser presets on one PC are not imported into this database by themselves. Save each material.

There is no file import for stock in this branch. Do not look for a CSV command.

The inventory plug-in of the Shop Connector is coming with the Shop Connector (PR #28, branch `shop-connector`). That plug-in is not in this checkout. This walkthrough does not give connector commands. Do not invent any.

## 7. Optional: connect to OUTPUT

OUTPUT sharing is optional and **off** by default. Nesting, stock, and saving a file do not use it. Nothing is sent until someone on the host pairs this computer and then turns sharing on. Designer PCs cannot pair, disconnect, or change that consent.

On first open, while this computer is not connected, the page shows **Connect to OUTPUT (optional)**. **Skip** opens the workspace and is remembered in that browser. **Have a pairing code?** is the pairing path on the host. **Set up your shop** stays hidden. `output_remote.READY` defaults to false, so browser-approval routes and stock-summary upload stay closed. A shop setting cannot turn that flag on. **Skip** works with that flag left false.

Leave this off unless the owner asked for it.

**Join OUTPUT network** (`outputNetwork` in `shop.json`) is a different switch. It is hidden, it stays off, and it sends nothing. Do not confuse it with the steps below.

### Get a pairing code

The host operator pastes a pairing code from OUTPUT. This repository does not contain the OUTPUT website. It does name the public site `https://output.jeezlabs.io/` and the waitlist at `https://output.jeezlabs.io/waitlist`. Pairing posts to `https://output.jeezlabs.io/api/shop/agent/pair`.

UNVERIFIED - confirm on a real PC: that the pairing code is shown on the OUTPUT site at `/outpost/ez-nest`. That path is not in this repository.

Do not write a real code, a shop key, or a token in this file, in `shop.json`, in a screenshot, or in a chat. The code is ten letters or digits. You may paste it with or without the hyphen. Ez Nest sends the uppercase hyphenated form. This page does not show an example code.

### Pair, on the host only

Do this in the browser on the host, while the `eznest` task is the program that is serving the page (the `eznest-svc` user). If you pair from a copy you started as a different Windows user, that user owns the key and `eznest-svc` cannot read it.

1. On the host, open `http://127.0.0.1:8765/web`.
2. Open **Settings** → **Share activity with OUTPUT**.
3. Paste the pairing code into **Pairing code**.
4. Choose **Connect**.
5. The page then asks you to review the fields and choose **Enable sharing**. Check **I agree to automatically share new activity using these fields**, then choose **Enable sharing**.

Connect alone does not send activity. **Enable sharing** is still required. Earlier activity is not uploaded for that consent.

On Windows the shop key is encrypted with DPAPI for the Windows user that saved it. DPAPI is Windows encryption tied to that user, not to every account on the PC. The machine-wide flag is not used. The file is `C:\ProgramData\eznest\output-credential.bin`. Its permissions allow SYSTEM, Administrators, `eznest-svc`, and the user who wrote the file. The Users group does not get the file.

### What is sent

The pairing request sends this computer's name and its installation id to OUTPUT, with the pairing code. The code and the shop key are not written to logs or to the page's API responses.

After **Enable sharing**, new local activity can be sent as `eznest-observation/1` events to `https://output.jeezlabs.io/api/shop/telemetry`. The settings page lists what those events include:

- a stable installation id, opaque layout and request ids, event time, app version, and event type
- a standard material category: `moto_regular`, `moto_holographic`, `moto_chrome`, `custom`, `unknown`, or null
- measurement ranges for length, width, area, unused printable percent, piece count, sheet count, search time, and stock

The host IP address and the shop credential go with those HTTPS requests. Measured stock readings already recorded on this host can be included. The stock ledger in `materials.sqlite3` is not uploaded. Exact quantities stay on the host.

### What is never sent

The settings page says these are never shared:

- artwork
- files or filenames
- customer names or contacts
- job codes
- roll ids
- custom material names
- exact dimensions, quantities, stock, and search time

### Disconnect

On the host, Settings → **Share activity with OUTPUT** → **Disconnect**. Confirm the question `Disconnect this computer from OUTPUT? Sharing stops until someone pairs again.`

That deletes the paired key file and stops later sends. It does not delete records OUTPUT already accepted. It does not remove a key that is coming from launch settings (`EZ_NEST_OUTPUT_UPLOADS=1` with `EZ_NEST_OUTPUT_TOKEN`). While those launch settings are present, disconnect is refused and a pairing code is not used. `EZ_NEST_OUTPUT_UPLOADS=0` turns delivery off.

**Stop sharing** stops later sends for the current consent. It is not the same button as **Disconnect**.

## 8. Verify it works

On the host and on one designer PC:

1. The designer PC opens `http://EXAMPLE-PC:8765/web` (the real host name; `https://` when the host was started with a certificate), enters the PIN, and the nest page loads. **Log out** returns to the PIN page.
2. Drop a test file, choose a material, and nest. **Review and save**, then **Save**, with **Save to** on the default print folder. The file appears in the host's hot folder. A save means the file reached the folder. It does not mean the job printed.
3. On one PC, **Save material** with a new length left on the roll. Within about ten seconds, the other PC shows that length. If it does not, refresh. Both PCs must be on the same host. `127.0.0.1` on the designer PC does not count.

These checks are for a person at the shop. This repository's inventory tests use two local HTTP clients, not two physical PCs.

### Troubleshooting

| What you see | What to check |
| --- | --- |
| The designer PC cannot open the page | The host is on, awake, and the `eznest` task is running **with** `--lan`. The PIN is saved. The address is the host's name or the host's own address, port 8765, path `/web`. The designer is not using `127.0.0.1`. The Windows profile on the host is Private, so the `eznest` firewall rule applies. Guest Wi-Fi and an internet forward of port 8765 are not used. |
| `Too many tries from this computer. Wait and try again.` | That address had five wrong PINs. The first wait is one minute. Each new lock for that same address waits twice as long, up to 64 minutes. Do not keep guessing. Other computers are not locked by this. Changing the PIN on the host signs every designer browser out. |
| The hot folder can't be reached, or `eznest cannot write to it` | The path is a real folder. The account that runs Ez Nest (`eznest-svc`) can write it. A share's permissions are not set by this installer. A UNC path is not granted automatically. Fix the path or the permission, then save the hot folder again on the host. The page does not pretend the job was sent. |
| Designer PCs cannot connect, and the host's network profile is Public | The firewall rule is Private only (`profile=private`). Public does not use it. Set the host network to Private. UNVERIFIED - confirm on a real PC: the Settings clicks for that change. |
| SmartScreen says it protected your PC | You are running an unsigned `eznest-setup.exe`. Compare the SHA-256 first. A mismatch means do not run the file. The README then says **More info**, then **Run anyway**. UNVERIFIED - confirm on a real PC: those button labels. |

## 9. For AI agents

You may:

- Read this file, the README, `SECURITY.md`, and the other docs.
- Generate a `shop.json` that uses the fields and the placeholder example above (`Example shop`, `EXAMPLE-PC`, `Example printer`, `C:\RIP\Example RIP Input`). No real shop name, hostname, IP, PIN, or key.
- Run this repository's tests.

You must not:

- Log into a shop PC remotely.
- Install Ez Nest on a PC without the owner's go, or without Iban's go.
- Handle a shop PIN, an OUTPUT pairing code, an OUTPUT shop key, a GitHub token, or any other secret. Do not ask for them to be pasted into chat. Do not write them into a file.
- Change firewall rules, including the `eznest` rule, `localsubnet`, and `-LanPeers`.
- Merge a pull request, or publish a release.

If a step above is marked **UNVERIFIED - confirm on a real PC**, do not fill the gap with a guess. Stop and say which step is unverified.
