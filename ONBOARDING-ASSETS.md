# Onboarding visuals

## Restored walkthrough

The active walkthrough is restored to commit `f141581` at the owner's request. The later OUTPUT-style artwork and motion documented below are retained in the repository for reference, but are no longer displayed, served, or packaged in this restored version. The original three-slide welcome and intent-specific Don't print popup are active.

## Retained design references

Bundled locally; onboarding makes no requests to the marketing sites.

The current welcome uses OUTPUT's actual computer, file, stickers and upload illustrations, with its original `ComputerIllustration` screen geometry. The first scene uses the site's stepped file-transfer and green receipt treatment, settles in 3.6 seconds and respects reduced motion. No visible playback bar. Type, color, hero spacing, highlighted job labels, white illustration stage, step layout and button treatment adapt `apps/web/app/experience/landing.module.css`; motion adapts `machine-illustration.module.css` (ezdesigns/output main, read 2026-11-04). The earlier custom roll drawing and custom icons are no longer used. OUTPUT examples retain compact accessible controls beside previous/next arrows.

`onboarding-file.webp` and `onboarding-upload.webp` are optimized copies of https://output.jeezlabs.io/illustrations/print-v2/file.png and https://output.jeezlabs.io/illustrations/print-v3/upload.png. These are bundled locally with the existing OUTPUT artwork. No remote embedding or OUTPUT connection is required.

- `onboarding-nest.webp`: https://eznest.jeezlabs.io/prototype/stills/hero-nest-d.webp
- `onboarding-nest.webm`: rendered from the SVG animation at https://eznest.jeezlabs.io/prototype/nesting.html on 2026-11-04. Shows the loose-parts, rows and nesting sequence only; no automatic cut generation or hot-folder delivery. Synthetic example, not measured savings. Colorfigures attribution and MIT terms are in `LICENSE-colorfigures.txt`.
- `onboarding-computer.webp`: optimized copy of https://output.jeezlabs.io/illustrations/print-v2/computer.png
- `onboarding-printer.webp`: optimized copy of https://output.jeezlabs.io/illustrations/print-v2/printer.png
- `onboarding-output.webp`: optimized copy of https://output.jeezlabs.io/illustrations/print-v3/output-square.png

OUTPUT artwork reused at the product owner's request from ezdesigns/output. The local three-part illustration adapts the current landing page's shop → OUTPUT → partner presentation, without connecting a shop or sending a job. The animation has pause/play controls, observes reduced motion, and stops on leaving the slide or hiding the page.

The six rotating examples adapt `apps/web/app/experience/landing-demo.ts` from ezdesigns/output (main, retrieved 2026-11-04): rush stickers, wider backdrop, distant delivery, spare capacity, business cards and T-shirts. They are illustrative scenarios, not live availability. Each cycles through need → matching → partner, with manual previous/next navigation.

Additional artwork is resized to at most 500px and encoded as WebP from the following OUTPUT public assets: `print-v3/stickers.png`, `print-v2/backdrop.png`, `print-v2/cards.png`, `print-v3/tshirts.png`, `print-v2/press.png`, `print-v3/screenpress.png`, under https://output.jeezlabs.io/illustrations/. Filenames in this bundle use the `onboarding-` prefix.
