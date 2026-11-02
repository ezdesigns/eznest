// QA-only observer of the installed signed App, with no production test hooks.
import AppKit
import CoreGraphics

let workspace = NSWorkspace.shared
let appURL = URL(fileURLWithPath: "/Applications/eznest.app")
let expected = appURL.appendingPathComponent("Contents/MacOS/eznest-desktop")
let browsers: Set<String> = ["com.apple.Safari", "com.google.Chrome", "org.mozilla.firefox",
    "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser"]
func browserPIDs() -> Set<pid_t> {
    Set(workspace.runningApplications.filter { browsers.contains($0.bundleIdentifier ?? "") }
        .map { $0.processIdentifier })
}
func spin(_ seconds: TimeInterval) { RunLoop.current.run(until: Date().addingTimeInterval(seconds)) }
func require(_ condition: Bool, _ message: String) {
    guard condition else { fputs("DESKTOP_FAIL: \(message)\n", stderr); exit(1) }
}
require(NSRunningApplication.runningApplications(withBundleIdentifier: "io.jeezlabs.eznest").isEmpty,
        "Existing desktop client prevents ownership.")
let before = browserPIDs()
require(before.isEmpty, "A running browser prevents proving no browser startup.")
var browserLaunched = false
let observer = workspace.notificationCenter.addObserver(
    forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main) { note in
    if let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
       browsers.contains(app.bundleIdentifier ?? "") { browserLaunched = true }
}
defer { workspace.notificationCenter.removeObserver(observer) }
var launched: NSRunningApplication?
var launchFailed = false
let configuration = NSWorkspace.OpenConfiguration()
configuration.activates = true
workspace.openApplication(at: appURL, configuration: configuration) { app, error in
    DispatchQueue.main.async { launched = app; launchFailed = error != nil }
}
let deadline = Date().addingTimeInterval(45)
while launched == nil && !launchFailed && Date() < deadline { spin(0.1) }
require(!launchFailed && launched != nil, "Applications launch failed.")
let client = launched!
defer { if !client.isTerminated { _ = client.terminate() } }
require(client.bundleIdentifier == "io.jeezlabs.eznest" && client.executableURL?.standardizedFileURL == expected,
        "LaunchServices selected an unexpected executable.")
var visible = false
while Date() < deadline && !client.isTerminated {
    let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                             kCGNullWindowID) as? [[String: Any]] ?? []
    visible = windows.contains { window in
        guard (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == client.processIdentifier,
              (window[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
              let bounds = window[kCGWindowBounds as String] as? [String: Any],
              let width = bounds["Width"] as? NSNumber,
              let height = bounds["Height"] as? NSNumber else { return false }
        return width.doubleValue >= 900 && height.doubleValue >= 600
    }
    if visible && client.activationPolicy == .regular { break }
    spin(0.2)
}
require(visible && client.activationPolicy == .regular, "No regular native application window.")
spin(5)
require(!client.isTerminated && !browserLaunched && browserPIDs() == before,
        "Desktop startup changed browser processes or exited unexpectedly.")
require(client.terminate(), "Desktop client refused Quit.")
let quitDeadline = Date().addingTimeInterval(15)
while !client.isTerminated && Date() < quitDeadline { spin(0.1) }
require(client.isTerminated, "Desktop client did not quit.")
print("DESKTOP_PASS: Applications native window; no browser launch; client Quit completed.")
