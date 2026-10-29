# Security

## Reporting a vulnerability

Report a security vulnerability through GitHub private vulnerability reporting:

https://github.com/ezdesigns/eznest/security/advisories/new

Open that page and choose **Report a vulnerability**. The report stays private between you and the maintainers. Do not file a public GitHub issue, and do not include customer artwork, shop files, or credentials.

Private vulnerability reporting has to be enabled in the repository security settings. If that page does not accept a report, use the contact email below.

### Contact email

**ezdesignstx@gmail.com**

## Shop network mode

**Stock database.** `materials.sqlite3` is opened only by the Ez Nest process on the host. Do not put it on an SMB share, a mapped drive, or another PC. Designer computers use the web page. They never open the database file.

Shop network is off until the host is started with `--lan`, and that start is refused until a shop PIN is saved on the host. The installer turns shop network on only when **Shop network** is selected. In that mode Ez Nest listens on all interfaces (`0.0.0.0`). Plain HTTP on port 8765 is the default. Local HTTPS is optional and is the recommended extra step below.

Use shop network only on a trusted private network. Do not forward port 8765, and do not put this host on the internet or on guest Wi-Fi.

Without `--lan`, Ez Nest binds to `127.0.0.1` only. A saved shop setting cannot open the listener by itself.

### Shop PIN

1. On the shop computer, open `http://127.0.0.1:8765/web`.
2. Open **Settings** and **Shop PIN**. Enter 8 to 12 digits, or a passphrase of at least 10 characters that includes a letter, and choose **Save shop PIN**. A PIN saved before this rule still works. Settings asks the host to replace it.
3. Restart Ez Nest with `--lan` (or reinstall with Shop network selected).
4. On each designer PC, open `http://SHOP-HOST:8765/web` and enter that PIN once. Choose **Log out** when finished. The browser keeps an HttpOnly, SameSite=Strict cookie for at most 8 hours, and for 60 minutes after the last request. The cookie is bound to that computer's address. It does not receive the host write token.

The PIN is stored as a salted scrypt hash in the host data directory. It is not written in plaintext. Five wrong tries from one address lock that address for one minute. Each later lock for that address waits twice as long, up to 64 minutes. A separate count of failures from every address, including a rotating set of addresses, shows a banner in Settings and writes a log line. That notice does not lock out the other computers. Changing the PIN signs every designer browser out.

### Plain HTTP and local HTTPS

On plain HTTP, anyone who can watch the shop LAN traffic can copy the session cookie and reuse it until it expires or the designer logs out. That is the residual risk of the default. The recommended extra step is a certificate on the host:

```text
openssl req -x509 -newkey rsa:2048 -keyout eznest-key.pem -out eznest-cert.pem -days 825 -nodes -subj /CN=SHOP-HOST
chmod 600 eznest-key.pem
```

On Windows, restrict the key before the shop task reads it. `eznest` is a scheduled task running as the user `eznest-svc`, not a Windows service:

```text
icacls eznest-key.pem /inheritance:r /grant:r *S-1-5-18:(R) *S-1-5-32-544:(R) eznest-svc:(R)
```

Ez Nest refuses to start HTTPS on Linux or macOS when the key is readable by the group or by other accounts. On Windows it applies that ACL when it can.

Start the host with both files:

```text
python launcher.py --web --lan --tls-cert eznest-cert.pem --tls-key eznest-key.pem
```

The Windows shop task can take the same pair as `-TlsCert` and `-TlsKey` on `install-shop.ps1`. Leave both empty to keep HTTP. Designers then open `https://SHOP-HOST:8765/web` and accept the certificate warning once, or install that certificate on those PCs. When Ez Nest is serving HTTPS, the session cookie is marked Secure. A self-signed certificate is not a public certificate authority. Keep port 8765 off the internet either way.

An IPv4-mapped IPv6 address such as `::ffff:127.0.0.1` is treated as `127.0.0.1`. `::ffff:` followed by any other IPv4 address is that IPv4 address for the PIN lock and the session binding.

Shop settings, first-time setup, the source-folder queue, the hot-folder connection, and the OUTPUT address can be changed only from the shop computer (`127.0.0.1`). After the PIN, designer browsers can still nest and use shared stock.

### Firewall

When Shop network is selected, setup adds an inbound rule named `eznest` for TCP 8765 on the **Private** profile only. The rule's `remoteip` is `localsubnet` unless you pass designer PC addresses:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install-shop.ps1 -DataDir C:\ProgramData\eznest -App "C:\Program Files\eznest\eznest.exe" -Lan 1 -StartAtBoot 1 -LanPeers "10.0.0.11,10.0.0.12,10.0.0.13"
```

Give those PCs static DHCP leases. Do not check Public if Windows asks.

### Data folder

Setup removes inherited permissions on `C:\ProgramData\eznest` and grants SYSTEM and Administrators full control, and `eznest-svc` modify. Other Windows users cannot replace `shop.json`.

`materials.sqlite3` stays in this folder. Only the host process may open it. Never place that file on an SMB share.

### Host header

A request is accepted only when the Host header is this computer's own name or one of its own addresses (`localhost`, loopback, or `lan_addresses()`), on the shop port. Another private IP is rejected. State-changing requests and `GET /api/session` also need a matching `Origin` or `Sec-Fetch-Site: same-origin`. A cross-site page is rejected. Loopback programs that send neither header (the launcher, Illustrator, the update helper) still work on this computer.

### OUTPUT connection

The shop computer must be paired with OUTPUT before nesting, sending, or stock changes. The API returns `connect_required` until then. Pairing, disconnect, and check-in are host-only. The address allowlist is unchanged: `https://output.jeezlabs.io`, or the exact origin in `EZ_NEST_OUTPUT_URL`.

The pairing code and the shop credential are not logged, not put in source, and not returned to the browser. Check-in sends the app version only. The computer name and installation id go out once, at pairing. Customer artwork, filenames, and stock contents are not part of either request.

A missing OUTPUT response does not stop a paired shop for 14 days (`CHECK_IN_MAX_AGE_DAYS`). OUTPUT saying the credential is revoked does. `EZ_NEST_DEV_NO_OUTPUT=1` is ignored unless the process is a source checkout in dev mode (`--dev`). Installed builds drop that variable. Forks may remove the requirement under Apache-2.0. Official builds enforce it.

### OUTPUT address and key

The OUTPUT address can be changed only on the shop computer. It must be `https://output.jeezlabs.io`, or the exact https origin in `EZ_NEST_OUTPUT_URL` set by an administrator before the process starts.

On Windows the OUTPUT shop key is encrypted with DPAPI for the Windows user that saved it, not for every account on the PC. Pair while the scheduled task named `eznest` is running as the user `eznest-svc`, so that account owns the key. That task is not a Windows service. The file ACL does not grant the Users group.

### Updates and the GitHub token

Update checks stay off unless `EZ_NEST_UPDATES=1` and the Settings box are both on. The installer default is off.

A public repository needs no token. Do not put a GitHub token in `shop.json` or in a `github-token` file. Those are ignored. Set `EZ_NEST_GITHUB_TOKEN` for the service process, or on Windows store a generic credential named `eznest/github-token`. If an old `github-token` file is still in the data folder, delete it.

### Dependency check

GitHub Actions billing may be blocked. On a machine with the requirements installed, run:

```text
python -m pip install pip-audit
python -m pip-audit -r requirements.txt
```
