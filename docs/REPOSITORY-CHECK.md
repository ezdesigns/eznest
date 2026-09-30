# Repository handoff check — 2026-09-30

This handoff prepares eznest 0.10.0-beta.1 for a new source repository. It adds repository documentation, ignore rules, line-ending settings and a Windows test workflow. Application code and the existing Windows executable are unchanged.

## Checked locally

- Ran the Python suite from the staged repository: **41 tests passed**.
- Ran JavaScript syntax, queue, physical-unit, profile-contract and seven boundary-policy checks from the staged repository: passed.
- Parsed the repository's Python files and confirmed `index.html` matches the served `production.html`.
- Verified application files match the tested source byte for byte. The Windows ZIP retains SHA-256 `384b1b9f7ae550facc7b527e533a33b004a6947da0d03584002fa02f64e45180`.
- Tested `.gitignore` with Git in a disposable local repository. Workstation state, virtual environments, browser/server export data, customer-file folders and generated binaries are ignored. Every file intended for this handoff remains trackable, including upstream license/source archives.
- Used an explicit source-file allowlist. No installed environment, customer design file, generated print pack, private shop notes, credentials file, workstation data or `.git` history is included.
- Scanned first-party text for workstation-specific paths and common credential patterns; none matched. This is a targeted handoff check, not a complete security audit.
- Included the third-party notices and upstream covered source required by the existing build script.

An initial full-suite run encountered Windows loopback error 10053 while checking an unauthorized request. The focused server suite and a complete rerun both passed without code changes. Inspect the first hosted Actions result after uploading.

## GitHub status

The workflow runs the same commands on a Windows-hosted runner with Python 3.12 x64 and Node 24. It uses read-only repository permissions and does not publish, deploy, create releases or require a personal access token. Workflow references were checked against the official action documentation on the preparation date.

The GitHub-hosted workflow has **not** run yet: no remote repository was created or uploaded by this handoff. The user will create the repository and publish the source using the included walkthrough.

The ZIP contains source files, not an initialized Git repository. GitHub Desktop creates the local history under the user's identity. The original-code license remains undecided; dependency licenses are preserved.

Current production limits remain those recorded in [the README](../README.md) and [packaged validation](../PACKAGED-VALIDATION.md).
