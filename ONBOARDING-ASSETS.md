# Onboarding visuals

Bundled locally; onboarding makes no requests to the marketing sites.

The current welcome uses an original code-native SVG drawing and three matching step icons in `shop-team.js`. Its introductory motion settles in under three seconds and respects reduced motion. It has no visible playback bar. The earlier still/video below remain bundled for provenance and compatibility but are no longer shown on the welcome. OUTPUT examples retain compact, accessible icon controls beside the previous/next arrows.

- `onboarding-nest.webp`: https://eznest.jeezlabs.io/prototype/stills/hero-nest-d.webp
- `onboarding-nest.webm`: rendered from the SVG animation at https://eznest.jeezlabs.io/prototype/nesting.html on 2026-11-04. Shows the loose-parts, rows and nesting sequence only; no automatic cut generation or hot-folder delivery. Synthetic example, not measured savings. Colorfigures attribution and MIT terms are in `LICENSE-colorfigures.txt`.
- `onboarding-computer.webp`: optimized copy of https://output.jeezlabs.io/illustrations/print-v2/computer.png
- `onboarding-printer.webp`: optimized copy of https://output.jeezlabs.io/illustrations/print-v2/printer.png
- `onboarding-output.webp`: optimized copy of https://output.jeezlabs.io/illustrations/print-v3/output-square.png

OUTPUT artwork reused at the product owner's request from ezdesigns/output. The local three-part illustration adapts the current landing page's shop → OUTPUT → partner presentation, without connecting a shop or sending a job. The animation has pause/play controls, observes reduced motion, and stops on leaving the slide or hiding the page.

The six rotating examples adapt `apps/web/app/experience/landing-demo.ts` from ezdesigns/output (main, retrieved 2026-11-04): rush stickers, wider backdrop, distant delivery, spare capacity, business cards and T-shirts. They are illustrative scenarios, not live availability. Each cycles through need → matching → partner, with manual previous/next navigation.

Additional artwork is resized to at most 500px and encoded as WebP from the following OUTPUT public assets: `print-v3/stickers.png`, `print-v2/backdrop.png`, `print-v2/cards.png`, `print-v3/tshirts.png`, `print-v2/press.png`, `print-v3/screenpress.png`, under https://output.jeezlabs.io/illustrations/. Filenames in this bundle use the `onboarding-` prefix.
