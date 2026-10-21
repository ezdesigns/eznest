# Contributing

Ez Nest is a local nesting tool for print shops. Read [GOALS.md](GOALS.md) before adding a feature. v1 nests files, adds cut marks, and sends them to the RIP hot folder. It does not send customer files off the shop PC.

## Setup

For testing with Codex and proposing an improvement, start with
[the contributor walkthrough and prompts](CONTRIBUTOR-CODEX.md). It creates a
separate source environment and test data without replacing a shop installation.

Use 64-bit Python 3.12.

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

The default listen address is `127.0.0.1`. Shop network requires `--lan`, which binds `0.0.0.0` and accepts this computer's name. A saved preference alone must never widen the listener. Do not make the page reachable on the public internet.

The boot task runs as `eznest-svc` with limited rights. That account is not an administrator. Do not run the task as SYSTEM, and do not put the account password in the repository or in the data folder.

## Updates and links

These can be set without changing code. Environment variables win. A one-line file in the data directory (`%ProgramData%\eznest` for an install, `.local` for a source checkout) is next. The defaults point at `ezdesigns/eznest`.

| Setting | Environment | Data file |
| --- | --- | --- |
| Release API | `EZ_NEST_RELEASE_API` | `release-api` |
| GitHub repository `owner/name` | `EZ_NEST_GITHUB_REPO` | `github-repo` |
| Token, optional | `EZ_NEST_GITHUB_TOKEN` | `github-token` |
| Report-a-problem link | `EZ_NEST_ISSUES_URL` | `issues-url` |

A public repository needs no token. Leave the token unset. The token is sent only to `github.com` and `api.github.com`. Do not commit a token, a certificate, or a password.

Test channel is off until the operator turns it on. Pre-releases are listed only then.

## Signing

The Windows installer workflow signs `eznest-setup.exe` when the `WINDOWS_CERT_BASE64` and `WINDOWS_CERT_PASSWORD` secrets are set. When they are empty, the step skips and the unsigned installer is still uploaded. Do not commit a certificate.

## Tests for the shop scripts

`tests/test_shop_scripts.ps1` checks `installer/install-shop.ps1` and `installer/uninstall-shop.ps1`. The Windows test workflow runs it.
`tests/test_update_helper.ps1` validates update coordination with system operations mocked. See [Windows update acceptance](docs/windows-updates.md) before enabling employee rollout. Browser tests require installed Chrome or Edge.

## Pull requests

Contributor PRs currently target `cursor/shop-open-handoff-9891`, the integration
branch behind draft PR #4. Start a separate branch for each improvement. The
owner's existing PR #4 retains its protected base; contributors must not target
or push to that shop branch. Verify these targets before submitting; after v1
merges, the owner will identify the next target. Do not assume `main` yet.

Do not commit customer files, tokens, or `.local/`. Do not publish a release or change who can see the repository from a pull request.

Say what a shop operator would notice. Keep the page to one screen.
