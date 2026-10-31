# Contributing

Ez Nest is a local nesting tool for print shops. v1 nests files, adds cut marks, and sends them to the RIP hot folder. It does not send customer files off the shop PC.

## Setup

Use 64-bit Python 3.12. A source checkout can use `python contributor.py setup` and `python contributor.py start` for an isolated `--shop-test` data folder. That does not replace a shop installation.

```powershell
py -3.12 -m venv .local/venv
.local/venv/Scripts/python.exe -m pip install -r requirements.txt
.local/venv/Scripts/python.exe -m pip install playwright
.local/venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
```

Node is only used to check the page. There is no npm install.

```powershell
node --check web.js
node tests/test_queue.cjs
node tests/test_shop_profiles.cjs
node tests/test_cut_mapping.cjs
node tests/test_production_features.cjs
node tests/test_boundaries.cjs
node tests/test_illustrator_bridge.cjs
pwsh -NoProfile -File tests/test_update_helper.ps1
```

GitHub Actions runs those checks on Windows, Python 3.12, and Node 24. The Windows installer workflow builds `eznest-setup.exe`. It does not publish a release unless someone pushes a `v*` tag.

## Version

`version.json` is the only version number. The installer, the app, and the workflow read it. Do not copy the version into another file.

## Shop server

The default listen address is `127.0.0.1`. Shop network requires `--lan`, which binds `0.0.0.0` only after a shop PIN is saved, and accepts this computer's own name and addresses. A saved preference alone must never widen the listener. Do not make the page reachable on the public internet.

The boot task runs as `eznest-svc` with limited rights. That account is not an administrator. Do not run the task as SYSTEM, and do not put the account password in the repository or in the data folder.

## Updates and links

These can be set without changing code. Environment variables win. A one-line file in the data directory (`%ProgramData%\eznest` for an install, `.local` for a source checkout) is next. The defaults point at `ezdesigns/eznest`.

| Setting | Environment | Data file |
| --- | --- | --- |
| Release API | `EZ_NEST_RELEASE_API` | `release-api` |
| GitHub repository `owner/name` | `EZ_NEST_GITHUB_REPO` | `github-repo` |
| Token, optional, private-repo mirrors only | `EZ_NEST_GITHUB_TOKEN`, or Windows credential `eznest/github-token` | not stored |
| Report-a-problem link | `EZ_NEST_ISSUES_URL` | `issues-url` |
| OUTPUT service origin | `EZ_NEST_OUTPUT_URL` | `outputUrl` in `shop.json` |
| Dev mode label (source checkout only) | `EZ_NEST_DEV=1` or `--dev` | not stored |
| Skip OUTPUT on a source checkout | `EZ_NEST_DEV_NO_OUTPUT=1` together with dev mode | not stored |
| Background update checks | `EZ_NEST_UPDATES` (`0` by default) | `updates` in `shop.json` (false by default) |

A public repository needs no token. `shop_deploy.github_token()` is optional and only for a private-repo mirror. Leave the token unset. Do not put it in `shop.json` or a `github-token` file; those are ignored. The token is sent only to `github.com` and `api.github.com`, and only while update checks are on. Do not commit a token, a certificate, or a password.

`EZ_NEST_OUTPUT_URL` is set by an administrator when the process starts. A saved `outputUrl` must be `https://output.jeezlabs.io` or that same https origin, and it can be changed only on the host. The account connection is required on official builds. Activity sharing stays off until the host agrees. `EZ_NEST_DEV_NO_OUTPUT=1` is ignored unless `--dev` (or `EZ_NEST_DEV=1`) is also set on a source checkout. Installed builds ignore it. The page then shows `DEV MODE: not connected to OUTPUT`. Forks may remove the connection requirement. `contributor.py start` sets both variables for a local trial. `EZ_NEST_UPDATES` defaults to `0`. Set it to `1` and turn **Check for updates** on before Ez Nest calls GitHub. Installing a checked download is still a separate click.

Check pinned dependencies when you change `requirements.txt`. Actions billing may be blocked, so run this locally:

```text
python -m pip install pip-audit
python -m pip-audit -r requirements.txt
```

Test channel is off until the operator turns it on. Pre-releases are listed only then.

## Signing

The Windows installer workflow builds an unsigned `eznest-setup.exe`. It does not read a certificate and it does not sign the file. Do not treat a CI artifact as a signed installer. Do not commit a certificate.

## Tests for the shop scripts

`tests/test_shop_scripts.ps1` checks `installer/install-shop.ps1` and `installer/uninstall-shop.ps1`. The Windows test workflow runs it.
`tests/test_update_helper.ps1` validates update coordination with system operations mocked. See [Windows update acceptance](docs/windows-updates.md) before enabling employee rollout. Browser tests require installed Chrome or Edge.

## Pull requests

Open a pull request against `main`. Start a separate branch for each improvement.

Do not commit customer files, tokens, or `.local/`. Do not publish a release or change who can see the repository from a pull request.

Say what a shop operator would notice. Keep the page to one screen.
