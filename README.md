# Ez Nest

[Goals](GOALS.md)

Ez Nest is a free, open-source, self-updating desktop nesting tool that any print shop can install in minutes. It nests files, adds cut marks, and sends them to the RIP hot folder.

It is built first for EZ Designs (Austin). The EZ Designs printer, cut names, and hot folder are a preset. Any other shop types its own. Later, and only if a shop opts in, Ez Nest is how shops join the OUTPUT print production network. That switch is off, and it sends nothing. See [Goals](GOALS.md).

**1.0.0-rc.4** is the shop release candidate. "Ez Nest" is the name of EZ Designs. The code is [MIT](LICENSE). Third-party notices stay in [THIRD_PARTY.md](THIRD_PARTY.md) and `licenses/`.

The page stays on this computer at `http://127.0.0.1:8765/web`. Shop network is off until you turn it on. Nothing leaves the shop unless you opt in.

## Install

One Windows PC runs Ez Nest. The other computers only open a browser. The shop PC does not need Python or Git.

1. Download `eznest-setup.exe` from the GitHub release, or from the Windows installer artifact if you are testing a build that is not released yet. Code → Download ZIP is source, not the app.
2. If `eznest-setup.exe.sha256` is beside it, compare that checksum with the file before you run it.
3. Close any older Ez Nest, including a build still using port 8765. `Stop EZ Nest.cmd` in the old folder does that.
4. Run `eznest-setup.exe`. It installs to `C:\Program Files\eznest` and adds a desktop shortcut.
5. Leave **Start eznest when Windows starts** on if this PC should be ready after a reboot. That task is named `eznest`. It runs as the local user `eznest-svc`, which is not an administrator. The task uses limited rights. The password is random and is not written into the Ez Nest folder.
6. Leave **Shop network** off unless other PCs on this network will open the page. Leave **Disable updates** unchecked unless this PC must not call GitHub.

The desktop shortcut opens the browser. The boot task does not. Closing the browser leaves Ez Nest running. `Stop EZ Nest.cmd` in the install folder stops it.

Settings and the hot-folder path for an installed copy live in `%ProgramData%\eznest`.

To build the installer on a Windows machine instead, install 64-bit Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
py -3.12 -m pip install -r requirements.txt -r requirements-build.txt
py -3.12 build_windows.py --out ..\eznest-build
```

The result is `installer\Output\eznest-setup.exe`. The version number comes from `version.json`.

## First run

The first time the page opens, it asks for four things:

- Hot folder, the RIP folder Send writes to
- Printer name
- Cut spot names, thru and kiss
- Units

**Use EZ Designs preset** fills today's EZ Designs values: the Epson SureColor S80600, CutContour thru and kiss names, and inches. Check **This PC holds the hot folder** when the folder is on this computer, and the preset uses the local path. Leave it off and the preset uses the share. You can type a different path. Nothing is connected until you save.

After that, the page is one screen. Drop the day's files, set the quantity, and Send.

| File | What Ez Nest needs |
| --- | --- |
| PDF | Closed cut strokes it can map, and a closed outer boundary for each piece. |
| AI | The same, saved with Create PDF Compatible File. If it cannot be read, the page says Save as PDF. |
| SVG | A grouped piece with a clipping outline, a cut contour, or a path named `EZN_BOUNDARY`. |

PDF and SVG do not share a batch. One batch holds 800 pieces. Width is the material. Length comes from the layout.

If Send cannot see the hot folder or the share, the page says so and does not pretend the job was sent. Check the path, and that this PC can open the share. A hot folder on another PC is a share. This installer cannot change that share's permissions. On the RIP PC, the account that runs Ez Nest needs write access to the folder.

Leave colors as they are in the file. Set the printer ICC and registration marks in the RIP.

## Update

**Update** is in the gear, with **What's new** and **Report a problem**.

Update looks for a newer release. It downloads the installer only when the SHA-256 sidecar matches, then installs it the next time Ez Nest starts. Install now restarts into that build. Shop settings and the hot folder stay. If the new build does not start, the previous build is put back. The helper writes `%ProgramData%\eznest\updates\helper.log`.

Pre-releases show up only when **Test channel** is on.

Updates are on unless you turn them off in the installer or the gear. While they are off, Ez Nest does not call GitHub and does not read a token.

A public repository needs no token. A private repository can set `EZ_NEST_GITHUB_TOKEN`, or a one-line token file at `%ProgramData%\eznest\github-token`. The token is sent only to GitHub. The release URL and the problem-report link can be changed without rebuilding. See [Contributing](CONTRIBUTING.md).

## Report a problem

**Report a problem** in the gear opens a GitHub issue with the version filled in. Write what you clicked and the words on screen. Do not attach customer artwork.

If an update rolled back, include `helper.log` and leave customer files out of it.

## Shop network

The default is this computer only: `http://127.0.0.1:8765/web`.

Shop network is off until you turn it on. There is no login. Anyone on the shop LAN can Send. Do not share this network with guest WiFi. Do not forward port 8765 to the internet.

1. Check Shop network in the installer, or in the gear after install.
2. Restart Ez Nest. The gear then shows `http://<this-computer>:8765/web`. Other PCs open that address. They do not install Ez Nest.
3. The installer opens Windows Firewall for TCP 8765 on the private profile only. It does not open a public profile.

`--lan` is the same choice from a shortcut or a command. A container can bind `0.0.0.0` without turning shop names on. That is not the shop network.

## OUTPUT

**Join OUTPUT network** is off. It sends nothing. If a shop turns it on later, the only things shared would be the machine list and free capacity, and only after that opt-in. Customer files stay in the shop.

## Limits

One material and up to 800 pieces. PDF import is 20 MB and 25 pages. No EPS, no DeviceN cut colors, no inventory, and no direct printer or cutter control. Nesting is heuristic. Read [supported files](docs/PRODUCTION-FILES.md).

Not in v1: job history, order intake, and cost tracking as a product.

## Develop

Contributing, tests, and the version source are in [CONTRIBUTING.md](CONTRIBUTING.md).

From source, with 64-bit Python 3.12:

```powershell
py -3.12 -m venv .local/venv
.local/venv/Scripts/python.exe -m pip install -r requirements.txt
.local/venv/Scripts/python.exe launcher.py --web
```

On Linux or macOS, use `python3` and `.local/venv/bin/python`. Then open `http://127.0.0.1:8765/web`.

```bash
docker build -t eznest .
docker run --rm -p 8765:8765 eznest
```

Older Illustrator scripts and the classic page are in [archive/](archive/README.md).

## License

Ez Nest is MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Dependencies keep their own licenses. See [THIRD_PARTY.md](THIRD_PARTY.md) and `licenses/`.
