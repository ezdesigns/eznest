# Security

## Reporting a vulnerability

Report a security vulnerability through GitHub private vulnerability reporting:

https://github.com/ezdesigns/eznest/security/advisories/new

Open that page and choose **Report a vulnerability**. The report stays private between you and the maintainers. Do not file a public GitHub issue, and do not include customer artwork, shop files, or credentials.

Private vulnerability reporting has to be enabled in the repository security settings. If that page does not accept a report, use the contact email below.

### Contact email

**[SECURITY-CONTACT-EMAIL-PLACEHOLDER]**

This is a placeholder. Replace `[SECURITY-CONTACT-EMAIL-PLACEHOLDER]` with the address that should receive vulnerability reports before anyone relies on email. Until then, use GitHub private vulnerability reporting.

## Shop network mode

Shop network is off until the host is started with `--lan`. The installer turns that on only when **Shop network** is selected. In that mode Ez Nest listens on all interfaces (`0.0.0.0`) and serves **plain HTTP on port 8765** (the default port, and the port the installer opens). There is no HTTPS and no login.

Use shop network only on a trusted private network. The firewall rule the installer adds, when Shop network is selected, allows inbound TCP 8765 on the **Private** profile only. It does not allow the Public profile. Do not check Public if Windows asks. Do not forward port 8765, and do not put this host on the internet or on guest Wi-Fi.

Without `--lan`, Ez Nest binds to `127.0.0.1` only. A saved shop setting cannot open the listener by itself. Only a start with `--lan` does that.

### `/api/session` and `X-EZ-Token`

`GET /api/session` does not require a password or the `X-EZ-Token` header. Any client that can reach the listener and pass the Host check receives a JSON body that includes `token`. The browser sends that value back as the `X-EZ-Token` header.

The token is created in memory when the process starts (`secrets.token_urlsafe`). It is not a user account. POST requests (import, nest, save to the hot folder, and the other shop actions) are rejected unless `X-EZ-Token` matches. If the browser sends an `Origin` header, that origin must name this host as well. A website on another origin cannot read `/api/session`, so it cannot forge a normal browser POST.

Anyone who can open `http://SHOP-HOST:8765/web` can call `/api/session`, copy the token, and use the shop. Several GET routes do not require the token at all once the Host header is accepted, including the current layout (`/api/state`), shop materials (`/api/materials`), and a saved pack download. The Host check allows this computer's name and private IP addresses. It is not a login.

OUTPUT pairing, sharing consent, and update approval are limited to the host itself (`127.0.0.1` plus `X-EZ-Token`). A designer PC on the shop network cannot turn sharing on.

Treat every computer that can reach port 8765 as a person who can nest and send jobs.
