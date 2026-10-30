# Signed Mac release procedure

Use a dedicated native Python 3.12 environment with `requirements-build.txt`.
Build and accept each architecture separately. An arm64 build does not certify
Intel. Preserve existing Windows release assets and the shop's data.

The commands below prepare a candidate; they do not authorize or prove public
release. Real installation, OUTPUT pairing and independent review are still
required. Never disable Gatekeeper or use an ad-hoc certificate to pass a gate.

## Prerequisites

- Local Keychain identities **Developer ID Application** and **Developer ID
  Installer**, both belonging to the approved publisher Team ID. Apple Development
  and 3rd Party Mac Developer Installer are not substitutes.
- A working `notarytool` Keychain profile. Provision it interactively; do not put
  Apple passwords or private keys in source, command arguments, logs or PRs.
- New output directories outside the source tree, adequate disk space, and a clean
  reviewed commit. Give PyInstaller its own `PYINSTALLER_CONFIG_DIR`.

## App signing and notarization

```sh
python build_macos.py --service-edition \
  --codesign-identity 'Developer ID Application: PUBLISHER (TEAMID)' \
  --out /absolute/new/app-build
```

The full identity is passed to PyInstaller so it signs the embedded Python,
extensions, libraries, executable and bundle with hardened runtime. No library
validation, JIT or debug entitlement is added. The build verifies the publisher,
hardened runtime and complete signature. Failure stops before creating an archive.
The embedded BUILD.json records build-time status; it cannot claim a future
notarization and is not modified after signing.

Submit the resulting architecture-specific ZIP:

```sh
xcrun notarytool submit /absolute/new/app-build/eznest-macos-ARCH-VERSION.zip \
  --keychain-profile PROFILE --wait --output-format json
```

Save the submission ID and response. Require status **Accepted**, not merely a
successful upload. If waiting times out, use `notarytool info` / `wait` with the
same submission ID; do not repeatedly submit the same bytes. For Invalid, retrieve
`notarytool log` and fix the reported cause before rebuilding.

```sh
xcrun stapler staple /absolute/new/app-build/dist/eznest.app
xcrun stapler validate /absolute/new/app-build/dist/eznest.app
spctl --assess --type execute --verbose=2 /absolute/new/app-build/dist/eznest.app
```

Require `source=Notarized Developer ID`. Stapling changes distributed bytes;
the earlier ZIP is a notarization submission artifact, not the final download.

## Shop installer signing and notarization

Use the stapled app with the existing guarded package builder. Default loopback
networking is intentional; `--lan` requires an explicit shop decision.

```sh
python build_macos_package.py --app /absolute/new/app-build/dist/eznest.app \
  --team-id TEAMID --out /absolute/new/package-build
productsign --sign 'Developer ID Installer: PUBLISHER (TEAMID)' \
  /absolute/new/package-build/eznest-shop-ARCH-VERSION-unsigned.pkg \
  /absolute/new/package-build/eznest-shop-ARCH-VERSION.pkg
xcrun notarytool submit /absolute/new/package-build/eznest-shop-ARCH-VERSION.pkg \
  --keychain-profile PROFILE --wait --output-format json
```

Again require **Accepted**, retain the submission receipt, then staple and validate
this package. Check `pkgutil --check-signature` and `spctl --assess --type install
--verbose=2`. The installed app and package must have the same approved Team ID.
Use `macos_update.verify_package` for the application's full publisher, notarization,
package identifier and version checks. Generate the final SHA-256 sidecar only after
stapling. The unsigned PACKAGE.json is preparation evidence, not a signed release
receipt; retain final checksums, Apple submission IDs and trust-command results
separately.

## Download-to-install acceptance and publication

On the intended architecture, download the exact candidate from a private/draft
release, check its digest and Gatekeeper assessment, and run Apple's Installer.
Do not overwrite an unrelated application or adopt existing user data. Confirm
launchd uses the limited `_eznest` account and normal mode, then use a clearly
labeled test shop to verify:

1. Unpaired access is locked; an OUTPUT account produces a one-time pairing code.
2. The installed host pairs, appears in that shop and advances a successful
   check-in timestamp, with activity sharing off.
3. Restart the service and verify another fresh successful check-in, then import,
   nest and export synthetic SVG/PDF work.
4. Owner revocation closes access and rejects further work. Revoke only this test
   host, preserve other bindings, and remove transient credentials.
5. Verify install/uninstall and required service/update recovery checks from
   `macos-shop-service.md`. Mocked trust responses and source-mode tests do not
   establish these results.

Independent review must inspect the exact source commit, signed candidate hashes,
required CI and actual runtime receipts. Publish only after these gates pass, then
verify anonymous download bytes match the reviewed final checksum and update the
landing page for the architectures actually accepted. Do not imply physical RIP,
printing, inventory synchronization or untested OS/architecture support.

References: [Apple Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates),
[Apple notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow),
[PyInstaller signing](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing).
