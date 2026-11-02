# Mac desktop window

The shop-service bundle opens its own AppKit window from Applications. WebKit
renders the existing full/simple workspace inside that window. No workspace
page is opened in Safari or Chrome during application startup.

The native client uses the one already installed shop service and its shared
data. It checks the fixed loopback session, exact application version and
launchd PID before loading. An unavailable or mismatched service displays a
native retry message; it never creates another server or Inventory database.

The Dock, menu bar, window reopening, file-import panel and download save panel
belong to the desktop client. Explicit OUTPUT/help links can open the default
browser. Remote pages, file URLs and arbitrary custom schemes cannot navigate
the workspace or use its file panels. There is no JavaScript filesystem or
command bridge.

Closing the window leaves the application available in the Dock; opening it
again restores the window. Quit EZNest closes the client. The installed shared
background service continues running, matching the existing service lifecycle.

## Bundle and verification

The native Finder entry is `Contents/MacOS/eznest-desktop`. The existing
`Contents/MacOS/eznest` stays the headless service/document/update executable.
The client and final bundle are signed after the native executable and metadata
are assembled. Existing publisher, architecture, notarization, package and
installed-service release gates remain required.

`Mac desktop window` CI compiles with Apple's SDK on macOS 26 and runs an
independent synthetic native UI verifier. It checks reopening, file input, blob
download bytes, loopback identity and redirect refusal. The test hooks are
compiled only into that separate verifier. CI also builds the actual combined
bundle and exercises its frozen SVG/PDF and restart flows with scratch data.

The CI candidate is ad-hoc signed and unnotarized, for review only. It is not a
public installer or an accepted managed upgrade. Version rc.7 is prepared so a
future installer can be distinct from the published rc.6 bytes. Source changes
do not replace an installed app, publish a release, alter OUTPUT consent, or
enable updates. Merging this new version after successful main CI triggers the
existing dual-platform release workflow, so merge and publication require the
owner's scoped release approval and all signed/installed-package acceptance.
