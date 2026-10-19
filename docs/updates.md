# Updates for testers

Ez Nest can replace its own portable Windows folder. The check looks for a newer build. **Update now** downloads it, verifies the checksum, and installs it on restart. **Install on next restart** does the same download and waits until the next launch. Jobs and settings stay. If the new build does not start, the previous build is put back.

The Windows portable workflow **builds** the ZIP, the SHA-256 file, and a manifest. It **does not publish a GitHub release** unless Ezven dispatches that step and the `eznest-release` environment approves it. An unpublished manifest is not offered to the app.

Code signing is not part of this. The checksum proves the file matches the manifest. It does not replace a Windows publisher certificate. SmartScreen can still warn on an unsigned exe.

## What the app does

The running build is the beta channel (`updateChannel` in `version.json`). A stable build only offers stable releases. A beta build offers the newest beta or stable version that is actually newer. It will not downgrade.

It looks, in order:

1. `EZ_NEST_UPDATE_MANIFEST_URL`, if that variable is set. That URL is the only source in that case, so a shop can point at its own HTTPS manifest.
2. Otherwise, the latest GitHub releases for `ezdesigns/eznest` (pre-releases count as beta; drafts are ignored), and the channel file `updates/beta.json` or `updates/stable.json` on the `main` branch.

A manifest is installable only when `published` is not `false` and the Windows entry has an HTTPS URL and a SHA-256 checksum. The files in this repository are intentionally unpublished, so they do not offer an update by themselves.

```json
{
  "channel": "beta",
  "version": "0.13.0-beta.1",
  "published": true,
  "notes": "Short text shown in What's new.",
  "platforms": {
    "windows-x64": {
      "filename": "eznest-0.13.0-beta.1-windows-x64.zip",
      "url": "https://github.com/ezdesigns/eznest/releases/download/v0.13.0-beta.1/eznest-0.13.0-beta.1-windows-x64.zip",
      "sha256": "64 lowercase hex characters"
    }
  }
}
```

`http://127.0.0.1` is allowed so tests can serve a manifest. Every other download must be HTTPS. A GitHub token in `EZ_NEST_GITHUB_TOKEN` is sent only to GitHub hosts, for a private repository. The token is not put in the page and not sent to any other site.

The ZIP is saved under `data\updates\incoming\`. If the checksum does not match, the file is discarded and nothing is replaced.

## Install and rollback

The app cannot overwrite `eznest.exe` while that exe is running. Update now closes the app and a helper copied under `data\updates\runner\` does the swap. On the next launch, the same helper runs before the window opens. Expect a short pause with no browser.

The helper:

1. Waits until Ez Nest has exited.
2. Checks the checksum and the version inside the archive again.
3. Copies the current app files to `data\updates\backup\`, skipping `data\`.
4. Replaces `eznest.exe`, `_internal`, and the other app files. Anything inside the archive named `data` is ignored.
5. Starts the new build and waits until it reports that it is listening.
6. If that does not happen, deletes the new files, restores the backup, writes `data\updates\rollback.json`, and starts the previous build.

What's new shows that rollback. The queue in the browser stays because the address is still `http://127.0.0.1:8765/`. Imported PDFs and frozen batches stay in `data\` beside the exe. Keep using the same browser.

Leave a few times the ZIP's size free on disk. The helper keeps a second copy of the app while it installs.

Set `EZ_NEST_UPDATES=0` to turn the check and the swap off. The packaged smoke test does that.

A source checkout (`python launcher.py`) will say when a newer build exists, and it will not replace the source tree. Install updates from `eznest.exe`.

## What Ezven publishes

Normal pushes and pull requests only upload workflow artifacts:

- `eznest-<version>-windows-x64.zip`
- `eznest-<version>-windows-x64.zip.sha256`
- `manifest-beta.json` with `"published": false` and no download URL

Testers download that artifact by hand for the first build. The app will not auto-install it.

To publish an update the app can install:

1. Create a GitHub environment named `eznest-release` on `ezdesigns/eznest`.
2. Add yourself (or Jerry, if he should approve) as a **required reviewer** before the first publish. Until reviewers are required, a dispatch could publish as soon as the button is pressed.
3. Run **Windows portable** with **Run workflow**. Set **publish_release** to true and choose `beta` or `stable`.
4. Approve the `eznest-release` environment when GitHub asks.
5. The job creates a GitHub release tagged `v<version>`, attaches the ZIP, the checksum, and `manifest-beta.json` or `manifest-stable.json`, and sets `published` to true. The download URL is the release asset URL. Beta is marked as a pre-release. A stable publish is refused if the version still has a prerelease suffix such as `-beta.1`.

Do not use that dispatch for a dry run. Artifact uploads already happen on every successful run.

The private repository means a tester's app can see a release only if GitHub can be read from that PC. For a private repo, set `EZ_NEST_GITHUB_TOKEN` to a fine-grained token that can read release assets, or set `EZ_NEST_UPDATE_MANIFEST_URL` to an HTTPS manifest whose `url` is a file the shop PC can download without GitHub. The checksum is still required.

`updates/beta.json` and `updates/stable.json` on `main` are the other channel files. They stay unpublished in git. After a release is approved, the release asset is the manifest the app reads. You do not have to commit a new manifest for the GitHub release path to work.

## What testers do

1. Install the first ZIP using [getting-started.md](getting-started.md).
2. Leave **What's new** available. Before any release is approved, it should say no newer build is published, or that the channel could not be reached if the repo is private and no token is set. Testing can continue either way.
3. When Ezven says a new build is approved, open What's new. **Update now** or **Install on next restart**.
4. After the app comes back, What's new should show the new version. If it restored the old one, use **Report a problem** and include `data\updates\helper.log` without customer files.

Stop a nest before updating. The app will refuse to restart in the middle of a search.
