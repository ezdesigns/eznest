# Security

## Reporting a vulnerability

Report a security vulnerability through GitHub private vulnerability reporting:

https://github.com/ezdesigns/eznest/security/advisories/new

Open that page and choose **Report a vulnerability**. The report stays private between you and the maintainers. Do not file a public GitHub issue, and do not include customer artwork, shop files, or credentials.

Private vulnerability reporting has to be enabled in the repository security settings. If that page does not accept a report, use the contact email below.

### Contact email

**ezdesignstx@gmail.com**

## Shop network mode

Shop network is off until the host is started with `--lan`, and that start is refused until a shop PIN is saved on the host. The installer turns shop network on only when **Shop network** is selected. In that mode Ez Nest listens on all interfaces (`0.0.0.0`) and serves **plain HTTP on port 8765**. There is no HTTPS.

Use shop network only on a trusted private network. Do not forward port 8765, and do not put this host on the internet or on guest Wi-Fi.

Without `--lan`, Ez Nest binds to `127.0.0.1` only. A saved shop setting cannot open the listener by itself.

### Shop PIN

1. On the shop computer, open `http://127.0.0.1:8765/web`.
2. Open **Settings** and **Shop PIN**. Enter 6 to 12 digits and choose **Save shop PIN**.
3. Restart Ez Nest with `--lan` (or reinstall with Shop network selected).
4. On each designer PC, open `http://SHOP-HOST:8765/web` and enter that PIN once. The browser keeps an HttpOnly, SameSite=Strict cookie. It does not receive the host write token.

The PIN is stored as a salted scrypt hash in the host data directory. It is not written in plaintext. Five wrong tries lock that computer out for one minute. Changing the PIN signs every designer browser out.

Shop settings, first-time setup, the source-folder queue, the hot-folder connection, and the OUTPUT address can be changed only from the shop computer (`127.0.0.1`). After the PIN, designer browsers can still nest and use shared stock.

### Firewall

When Shop network is selected, setup adds an inbound rule named `eznest` for TCP 8765 on the **Private** profile only. The rule's `remoteip` is `localsubnet` unless you pass designer PC addresses:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install-shop.ps1 -DataDir C:\ProgramData\eznest -App "C:\Program Files\eznest\eznest.exe" -Lan 1 -StartAtBoot 1 -LanPeers "10.0.0.11,10.0.0.12,10.0.0.13"
```

Give those PCs static DHCP leases. Do not check Public if Windows asks.

### Data folder

Setup removes inherited permissions on `C:\ProgramData\eznest` and grants SYSTEM and Administrators full control, and `eznest-svc` modify. Other Windows users cannot replace `shop.json`.

`materials.sqlite3` is opened only by the Ez Nest process on that host. Do not put it on an SMB share or copy it to designer PCs. Designer computers use the page on the host. They do not open the database file.

### Host header

A request is accepted only when the Host header is this computer's own name or one of its own addresses (`localhost`, loopback, or `lan_addresses()`), on the shop port. Another private IP is rejected. State-changing requests and `GET /api/session` also need a matching `Origin` or `Sec-Fetch-Site: same-origin`. A cross-site page is rejected. Loopback programs that send neither header (the launcher, Illustrator, the update helper) still work on this computer.

### OUTPUT address and key

The OUTPUT address can be changed only on the shop computer. It must be `https://output.jeezlabs.io`, or the exact https origin in `EZ_NEST_OUTPUT_URL` set by an administrator before the process starts.

On Windows the OUTPUT shop key is encrypted with DPAPI for the Windows user that saved it, not for every account on the PC. Pair while the `eznest-svc` service is running so that account owns the key. The file ACL does not grant the Users group.

### Updates and the GitHub token

Update checks stay off unless `EZ_NEST_UPDATES=1` and the Settings box are both on. The installer default is off.

A public repository needs no token. Do not put a GitHub token in `shop.json` or in a `github-token` file. Those are ignored. Set `EZ_NEST_GITHUB_TOKEN` for the service process, or on Windows store a generic credential named `eznest/github-token`. If an old `github-token` file is still in the data folder, delete it.

### Dependency check

GitHub Actions billing may be blocked. On a machine with the requirements installed, run:

```text
python -m pip install pip-audit
python -m pip-audit -r requirements.txt
```
