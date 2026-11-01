# Automatic Windows and Mac releases

The owner-selected policy is: update `version.json` in a reviewed PR, merge it,
then publish only after successful main CI and both platform gates. The workflow
does not invent version numbers or replace an already published version.

## Trigger and source

`auto-release.yml` reacts to completion of **Tests** on a same-repository `main`
push. PR/fork runs, unsuccessful CI, another workflow and stale main commits
cannot publish. The planner reads the version from the checked commit and uses
`v<VERSION>`. An existing published version is a no-op. A new version must be
newer than every published supported application version. Stable versions use
GitHub's latest designation; alpha/beta/rc versions remain prereleases.

The initial workflow rollout kept the already published `1.0.0-rc.5` unchanged.
A subsequent version-bump PR activates the build path; existing versions remain a no-op.

## Platform gates

- Windows reuses `windows-installer.yml`, including pinned Inno Setup, checksums,
  source/version pin and an actual fresh install on the disposable Windows VM.
  It still produces an **unsigned Windows preview**. The old tag-only publisher
  is removed; tags/PR/manual runs can build candidates but cannot publish alone.
- Mac runs on a disposable GitHub-hosted macOS 26 Apple-Silicon VM. It requires
  the approved publisher's Developer ID Application and Installer identities.
  Both app and package must receive **Accepted** from Apple, be stapled and pass
  Gatekeeper. Signing material uses a temporary Keychain and private files,
  removed before runtime/browser acceptance. Dependency installation has no
  signing secrets in its environment.
- Mac then installs the exact signed package as the limited shop service, tests
  local synthetic PDF/SVG import/nest/export and restart persistence with updates,
  LAN and sharing off, and cleans up only that VM's owned installation. These
  checks use no OUTPUT pairing code or real shop account.

Both jobs must succeed before the only `contents: write` publishing job runs.
It rechecks main/source/version, platform receipts and final file hashes, uploads
both platforms to a draft, verifies the uploaded hashes, then makes it public.
Unexpected draft assets or conflicting hashes stop publication. Nothing uses
`--clobber`. A matching partial draft can resume missing uploads; published
versions and draft assets with different bytes are preserved. For an interrupted
publish, rerun **failed jobs**, retaining the successful build artifacts. Rebuilding
the entire workflow can legitimately produce different signed bytes and will not
overwrite a partial draft with them.

## Required protected Mac configuration

An owner must provision these secrets in the `eznest-release` environment (or
repository, according to the repository's existing protection policy):

| Secret | Content |
| --- | --- |
| `MACOS_CERTIFICATE_BASE64` | Base64 P12 containing the Application and Installer signing identities |
| `MACOS_CERTIFICATE_PASSWORD` | P12 import password |
| `MACOS_APP_IDENTITY` | Full `Developer ID Application: … (JC6858UYM9)` identity |
| `MACOS_INSTALLER_IDENTITY` | Full `Developer ID Installer: … (JC6858UYM9)` identity |
| `MACOS_NOTARY_KEY_BASE64` | Base64 App Store Connect notarization API `.p8` key |
| `MACOS_NOTARY_KEY_ID` | Notarization API key ID |
| `MACOS_NOTARY_ISSUER_ID` | Notarization API issuer UUID |

Keep existing environment reviewer/branch protections. This change does not
provision credentials or remove approvals. The repository secret listing was
empty during implementation; environment configuration could not be inspected
with the available non-admin token. The Mac job reports missing configuration
and blocks the entire release; it never substitutes an ad-hoc package.

## Proof and limits

This is an automatic **experimental preview** release gate, not broad shop
rollout acceptance. Source tests and mocked signing/API fixtures validate the
policy and failure behavior; they do not establish a real signed CI build until
that path actually runs with protected credentials.

Live OUTPUT pairing/check-in/revocation stays in the separately dispatched
acceptance workflows, with an owner-approved test shop. No automatic live payment,
printing, shop provisioning or production database changes are part of this
workflow. Apple Silicon/macOS 26, new test installations, synthetic files and
updates off remain the preview scope. Intel, production RIP/cutting, signed
upgrade/rollback, reboot/logout longevity and normal user uninstall remain
separate acceptance work. Closing the browser does not stop the installed service.

The landing site's download links are currently pinned to `rc.5`; publishing a
GitHub release does not deploy the separate landing repository or change those
links. Update its pinned version/links through that repository's normal workflow.

See [manual Mac release and broader acceptance](macos-release.md) for the separate
trust and runtime checks. The automatic policy is tested in
`tests/test_auto_release.py`; no test publishes a real release.
