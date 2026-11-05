# One host, one shop update

The user-mode Windows host checks a fixed public downloads repository. The source
remains private. Designers use the host's address in a browser and do not need
GitHub access or their own app installation. Separately installed hosts update
separately; this does not synchronize independent inventories.

## Operator experience

1. Update checks stay off until the host enables **Settings > App updates**.
   Once enabled, portable installations check at startup and every six hours.
   An existing saved opt-out and `EZ_NEST_UPDATES=0` are respected.
2. A notice appears at the bottom left when a newer published release is
   available. Choose **View update** to review it in Settings, then **Update shop**
   on the host PC after saving the current print file or starting over.
3. Ez Nest verifies the download, backs up the application, replaces its app
   files and restarts on the same port with the same data folder and network mode.
   The previous application is restored if the replacement cannot start.
4. Connected browsers reload when idle. A browser with a file, an open dialog or
   a field being edited offers **Refresh app** instead of discarding edits.

The installation request is host-only and serialized with imports, exports and
job changes. A running search or unsaved result blocks restart. A downloaded ZIP
does not authorize installation on a later launch. Explicit installation is
required. OUTPUT pairing, stock sharing and capacity sharing are not enabled by
the updater. The updater never consults GitHub credentials in this edition.

## Free pilot distribution

Create **ezdesigns/eznest-downloads** as a public repository, initialized with a
README only. It holds binary release assets, checksums and release notes. Do not
copy the private source, customer artwork, shop data or credentials there.

This edition uses GitHub HTTPS. A shop update is installed only when
`update-manifest.json` verifies with the pinned public key and the download
matches the hash in that manifest. A release with no manifest is not installed.
A manifest marked as a database change is not installed. If the new build does
not start, the previous app files are restored. That restore does not undo a
database change.

The manifest is signed with a key kept offline. The private key is not in this
repository, in CI, or on the shop PC. This is not an Authenticode publisher
signature. The Program Files installer keeps its separate signed-publisher
requirement.

GitHub documents release downloads with no total release-size or bandwidth limit
(individual assets must be under 2 GiB):
<https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases>.
Private Actions build minutes remain subject to the account's plan. Local builds
avoid that build-minute cost. Public downloads do not require shop credentials.

## Release a new version

1. Merge reviewed code only after required checks pass. Bump `version.json` to a
   new version in a reviewed change; never replace bytes under a published version.
   Include the OUTPUT onboarding fix before replacing the existing pilot.
2. On main, run **Shop host portable build** in Actions. It runs source tests,
   builds the app and rehearses an actual frozen update and rollback with only
   synthetic local data. Download `shop-host-download` only from a successful run.
   Keep its `shop-host-update-receipt` and source commit for release records.
3. Alternatively, build from the same clean, tested main commit on a build PC:

   ```powershell
   python build_windows.py --portable-only --shop-portable --out C:\eznest-portable-build
   python tests/shop_portable_smoke.py --zip C:\eznest-portable-build\download\eznest-shop-windows.zip --work C:\eznest-portable-rehearsal
   ```

   Use new dedicated folders. Run required source checks as well. Do not package
   a running shop directory. The packager refuses unexpected files and shop data.
4. Sign `update-manifest.json` for that zip (see below). In the public downloads
   repository, create a draft release tagged `v` plus the exact version in
   `version.json`. Add the source commit to its notes. Upload
   `eznest-shop-windows.zip`, `eznest-shop-windows.zip.sha256`, and
   `update-manifest.json`. Mark release candidates as **pre-release**.
5. Check the manifest with the helper, then publish the draft. Hosts on the
   appropriate channel discover it at their next check. Publication is deliberate;
   merging a PR alone does not release binaries or restart shops.

There is no cross-repository publishing token in the app or this workflow. An
authorized release operator publishes through GitHub. Do not give designers the
publisher's account or copy its credentials into the shop.

## Sign an update manifest

Create the signing key on a machine that does not run the shop. Keep the private
key outside this repository. Do not commit it.

1. Generate a key. These paths are examples; choose a folder of your own:

   ```text
   python tools/sign_update_manifest.py keygen --private C:\secure\eznest-update.key --public C:\secure\eznest-update.pub
   ```

2. Copy the printed public key into `PUBLIC_KEY` in `update_manifest.py`.
   Review that change. The pin already in the file has no private key in this
   repository, so replace it before you sign a release.

3. Sign the exact file you will upload. Use the version from `version.json`
   without a leading `v`. For the shop host zip:

   ```text
   python tools/sign_update_manifest.py sign --private C:\secure\eznest-update.key --file C:\build\eznest-shop-windows.zip --version 1.2.3 --out C:\build\update-manifest.json
   ```

   The same command signs `eznest-setup.exe` when that is the release file.
   Add `--schema-change` only when the release changes the shop database. The
   updater refuses those releases. Leave the flag off when the previous app can
   still read the database.

4. Check the manifest, then upload `update-manifest.json` with the release.
   Do not upload the private key.

   ```text
   python tools/sign_update_manifest.py verify --public C:\secure\eznest-update.pub --file C:\build\eznest-shop-windows.zip --manifest C:\build\update-manifest.json
   ```

## First installation / existing pilot

Extract the entire ZIP into a new user-writable application folder, then open
`Start EZ Nest.cmd`. It requests shop LAN mode but remains loopback-only until a
shop is configured, following the existing authentication rules. Invite designers
through the shop UI. The host must remain running; this edition does not install
a Windows service or start at boot.

For the existing isolated pilot, keep its separate data directory and port 8766.
Use the equivalent explicit launch arguments with the new executable. Remove an
old `EZ_NEST_UPDATES=0` override only from that pilot's launcher and opt in through
Settings. Never replace the old Program Files installation, the old shop data or
credentials. Do not extract a new release over a running app. Bootstrap once into
a new folder; subsequent updates use the in-app button.

## Acceptance limits

The local regression tests cover host-only approval, active-job blocking, public
feed selection, corrupt-download rejection, unchanged inventory, preserved port
and LAN flags, two browser views and unsaved-edit protection. They also refuse a
bad signature, a changed download, a missing manifest, and a release marked as a
database change. The explicit frozen
rehearsal tests replacement and rollback on a disposable folder on one Windows PC.
It is not proof of a second physical PC, reboot persistence or a public release
download. Complete those pilot checks before broad rollout. Source builds do not
enable this edition: only a packaged host with its edition marker uses this feed.
Rollback restores application files, not database schema migrations. Release
changes to shop databases must remain readable by the previous app; rehearse with
an existing synthetic stock database and outstanding reservations before publishing.
