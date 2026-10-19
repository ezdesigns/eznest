# Plan: local one-page web nest

[Pull request #1](https://github.com/ezdesigns/eznest/pull/1) (`cursor/eznest-web-mvp-8f6a`) is the one-page shop nest. It is not a small change, so it is not in the tester build.

The pull request is about 2,800 lines across 37 files. It adds `web.html`, `web.js`, and `web.css`, changes the nesting engine, PDF import, packaging, and launcher, raises the batch cap from 100 pieces to 800, and renames the product version to `1.0.0-rc.1`. The page drops artwork, nests immediately, and sends one package toward ONYX. That is a different app from the 0.12 queue testers are about to use.

Shipping both in one ZIP would make the MX comparison ambiguous: testers would not know which screen, which piece cap, or which cut-spot defaults they measured.

## Land it on its own

1. Finish the 0.12 tester channel first: portable ZIP, What's new, updates, and the MX comparison in [testing-plan.md](testing-plan.md).
2. Keep pull request #1 open. Rebase it onto `main` after the tester work merges, and resolve the overlap in `server.py`, `launcher.py`, `build_windows.py`, `version.json`, and `.github/workflows/test.yml`.
3. Decide the cut-spot pair with Ez Ink before calling that page v1. The pull request's notes use `LNThru-cut` / `LNKiss-cut` as a shop default. The 0.12 beta writes `CutContour_Thru-cut` / `CutContour_Kiss-cut` and only treats the LN names as source aliases. ONYX has not confirmed either pair.
4. Give the one-page nest its own portable ZIP and its own smoke test. Do not replace the 0.12 exe testers already have until someone chooses that the one-page screen is the shop UI.
5. Keep job history, order intake, and cost tracking out of that page, which is what the pull request already claims. The update channel in [updates.md](updates.md) can carry whichever build is approved later.

## Risks to check when it is rebased

- Port 8765: a 0.12 process and a 1.0 process will not run together. The launcher already refuses a different version on that port.
- Browser data: the one-page page is a different URL (`/web`). The 0.12 queue in IndexedDB will not move across by itself.
- Piece cap and sheet split (800 pieces, 96 inch sheets, mark margins) change the numbers in an MX comparison. Record which build produced them.
- `eznest-web.bat` must be copied by `build_windows.py` or the shop double-click will not exist in the ZIP.

No license was chosen for that pull request either. Leave the license decision with Ezven.
