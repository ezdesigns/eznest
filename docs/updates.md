# Updates for testers

eznest can replace the shop install. **Update**, in the gear, looks for a newer GitHub release. If it finds one, it downloads `eznest-setup.exe` (or a zip of the app files), checks the SHA-256 checksum, and installs it the next time eznest starts. **Install now** does that restart immediately. Shop settings and the hot-folder path stay. If the new build does not start, the previous build is put back.

The Windows installer workflow **builds** the setup program, the SHA-256 file, and a manifest. It **does not publish a GitHub release** unless that step is approved in the `eznest-release` environment. An unpublished manifest is not offered to the app.

Code signing is not part of this. The checksum proves the file matches the release. It does not replace a Windows publisher certificate. SmartScreen can still warn on an unsigned setup program.

## What the app does

The running build looks at the recent GitHub releases for `ezdesigns/eznest`, including pre-releases. Drafts are ignored. It will not install an older version.

A release is installable when it has `eznest-setup.exe` (or a `.zip` of the app) and a checksum. The checksum is the sibling file `eznest-setup.exe.sha256`, or a published `manifest.json` on that release with the same filename and SHA-256. If the checksum is missing, or the download does not match, nothing is replaced.

The file is saved under `%ProgramData%\eznest\updates\incoming\`. The app files live in `C:\Program Files\eznest`. Settings and the hot folder live in `%ProgramData%\eznest`:

- `shop.json` — this PC runs ONYX, and shop network
- `output-folder.json` — the hot-folder path

An upgrade does not run the first-install script that writes those files. After a swap, eznest copies those two files back anyway, including when the new build does not start.

`http://127.0.0.1` is not used for release downloads. Every download is HTTPS on GitHub. A token in `EZ_NEST_GITHUB_TOKEN`, or in `%ProgramData%\eznest\github-token`, is sent only to GitHub hosts, for a private repository. It is not put on the page and not sent to any other site.

Set `EZ_NEST_UPDATES=0` to turn the check off.

A source checkout (`python launcher.py`) will say when a newer build exists. It will not replace the source tree. Install updates from the shop PC.

## Install and rollback

eznest cannot overwrite `eznest.exe` while that exe is running. Install now closes the app. A helper copied under `%ProgramData%\eznest\updates\runner\` does the swap. On the next launch, the same helper runs before the page opens. Expect a short pause with no browser.

The helper:

1. Waits until eznest has exited.
2. Checks the checksum again.
3. Copies the current app files aside, skipping the data directory.
4. Updates a writable portable installation from the checked package. Anything named `data` inside a zip is ignored. Program Files installations require the manual installer.
5. Puts `shop.json` and `output-folder.json` back.
6. Starts the new build and waits until it reports that it is listening.
7. If that does not happen, deletes the new files, restores the copy, writes `updates\rollback.json`, and starts the previous build.

What's new shows that rollback. The browser queue stays because the address is still `http://127.0.0.1:8765/web`.

The startup task runs as limited `eznest-svc`, which cannot overwrite Program Files. This updater keeps that server running and leaves the checked setup program in the updates folder. An administrator must run `eznest-setup.exe` manually. The portable helper rollback described above does not certify a manual Program Files upgrade.

Leave a few times the installer's size free on disk. The helper keeps a second copy of the app while it installs.

Stop a nest before updating. The app will refuse to restart in the middle of a search.

## What Ezven publishes

Normal pull requests and a manual run only upload workflow artifacts:

- `eznest-setup.exe`
- `eznest-setup.exe.sha256`
- `manifest.json` with `"published": false`

Testers download that artifact by hand for the first build. The app will not auto-install it.

To publish an update the app can install:

1. Create a GitHub environment named `eznest-release` on `ezdesigns/eznest`.
2. Add yourself (or Jerry, if he should approve) as a **required reviewer** before the first publish. Until reviewers are required, a tag or a dispatch could publish as soon as the job starts.
3. Either push a `v*` tag, such as `v1.0.0-rc.2`, or run **Windows installer** with **publish_release** on.
4. Approve the `eznest-release` environment when GitHub asks.
5. The job creates or updates the GitHub release, and attaches the setup program, the checksum, and `manifest.json` with `"published": true`. The release is marked as a pre-release.

Do not use that dispatch for a dry run. Artifact uploads already happen on every successful run.

The private repository means a tester's app can see a release only if GitHub can be read from that PC. For a private repo, set `EZ_NEST_GITHUB_TOKEN` to a fine-grained token that can read release assets. The checksum is still required.

## What testers do

1. Install the first setup program using [getting-started.md](getting-started.md).
2. Open the gear and click **Update**. Before any release is approved, it should say this is the latest release, or that the release could not be reached if the repo is private and no token is set. Testing can continue either way.
3. When Ezven says a new build is approved, open the gear. **Update** checks the file and waits for the next start. **Install now** restarts into it. The hot-folder path in the gear should be the one you set.
4. After the app comes back, the gear should show the new version. If it restored the old one, use **Report a problem** and include `%ProgramData%\eznest\updates\helper.log` without customer files.
