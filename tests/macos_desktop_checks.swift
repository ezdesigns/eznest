import AppKit
import WebKit

// Compiled only into the disposable native verifier, never the shipped app.
@MainActor final class DesktopChecks {
    let app: DesktopApp
    let folder: URL
    let mode: String
    var stage = 0
    var externalCount = 0
    var picker = false
    var save = false
    var finished = false
    var popupCreations = 0
    var popupClicks = 0
    var updateRequests = 0

    init(origin: URL, pid: Int, folder: URL, mode: String) {
        self.folder = folder; self.mode = mode
        let config = DesktopConfiguration(origin: origin, version: "1.0.0-rc.6", servicePID: { pid })
        precondition(config.contains(origin))
        for url in ["http://localhost:\(origin.port!)/", "https://127.0.0.1:\(origin.port!)/",
                    "http://127.0.0.1:1/", "http://evil@127.0.0.1:\(origin.port!)/", "file:///tmp/"] {
            precondition(!config.contains(URL(string: url)!))
        }
        app = DesktopApp(configuration: config)
        app.failed = { [weak self] _ in
            guard let self else { return }
            self.check(self.mode != "valid", "unexpected startup failure")
            self.complete(["closedOnInvalidService": true])
        }
        app.externalLink = { [weak self] url in
            guard let self else { return }
            self.check(url.absoluteString == "https://output.jeezlabs.io/workspace", "unexpected external URL")
            self.externalCount += 1
        }
        app.popupCreated = { [weak self] in self?.popupCreations += 1 }
        app.updateRequested = { [weak self] in self?.updateRequests += 1 }
        app.pickFiles = { [weak self] parameters in
            guard let self else { return nil }
            self.check(parameters.allowsMultipleSelection, "multiple-file picker contract")
            self.picker = true
            return [folder.appendingPathComponent("synthetic.txt")]
        }
        app.saveDownload = { [weak self] filename in
            guard let self else { return nil }
            self.check(filename == "native-export.txt", "download name")
            self.save = true
            return folder.appendingPathComponent(filename)
        }
        app.downloadFinished = { [weak self] in self?.verifyDownload() }
        app.loaded = { [weak self] in self?.loaded() }
    }

    func check(_ condition: Bool, _ name: String) {
        if !condition {
            fputs("NATIVE_FAIL: \(name)\n", stderr)
            exit(1)
        }
    }

    func js(_ script: String, then: @escaping (Any?) -> Void = { _ in }) {
        app.webView.evaluateJavaScript(script) { result, error in
            self.check(error == nil, "JavaScript stage \(self.stage)")
            then(result)
        }
    }

    func loaded() {
        check(mode == "valid", "invalid service loaded a workspace")
        check(NSApp.activationPolicy() == .regular, "normal desktop activation")
        check(app.window.title == "EZNest" && app.window.isVisible, "native titled window")
        check(NSApp.mainMenu?.items.count == 3, "native menu bar")
        if stage == 0 {
            check(externalCount == 0, "startup must not open a browser")
            app.window.close()
            _ = app.applicationShouldHandleReopen(NSApp, hasVisibleWindows: false)
            check(app.window.isVisible, "Finder/Dock reopen")
            stage = 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                self.check(self.externalCount == 0, "unsolicited popup must not open a browser")
                self.js("document.querySelector('#file').click()")
                self.waitForImport()
            }
        } else if stage == 2 {
            check(app.webView.url?.query == "view=simple", "mode navigation stays in app")
            stage = 3
            js("document.querySelector('#bad').click()")
            clickPopup()
        }
    }

    func clickPopup() {
        popupClicks += 1
        js("(() => {const r=document.querySelector('#popup').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()") { value in
            guard let coordinates = value as? [Double], coordinates.count == 2 else {
                self.check(false, "popup button position"); return
            }
            // Native events in this disposable CI window exercise WebKit's real
            // user-gesture gate; JavaScript .click() must not stand in for it.
            let view = self.app.webView!
            let y = view.isFlipped ? coordinates[1] : view.bounds.height - coordinates[1]
            let point = view.convert(NSPoint(x: coordinates[0], y: y), to: nil)
            for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
                guard let event = NSEvent.mouseEvent(with: type, location: point, modifierFlags: [],
                    timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: self.app.window.windowNumber,
                    context: nil, eventNumber: 1, clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0) else {
                    self.check(false, "native click event"); return
                }
                NSApp.sendEvent(event)
            }
            self.waitForPopup()
        }
    }

    func waitForPopup() {
        if popupClicks == 1 && popupCreations == 1 && app.pendingPopupCount == 0 {
            check(externalCount == 0, "closed popup must not open a browser")
            clickPopup()
        } else if popupClicks == 2 && externalCount == 1 {
            check(popupCreations == 2, "closed blank popup can be retried")
            check(app.webView.url?.host == "127.0.0.1", "external popup must not replace workspace")
            js("document.querySelector('#external').click()")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                self.check(self.externalCount == 2, "explicit external link")
                self.js("location.href='eznest-update://install?file=/tmp/untrusted.pkg'")
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                    self.check(self.updateRequests == 0, "reject update URL arguments")
                    self.js("document.querySelector('#update').click()")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                        self.check(self.updateRequests == 1, "fixed update action preserved without a browser")
                        self.js("document.querySelector('#download').click()")
                    }
                }
            }
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.waitForPopup() }
        }
    }

    func waitForImport() {
        js("document.body.dataset.imported || ''") { result in
            if result as? String == "synthetic native import" {
                self.check(self.picker, "WebKit invoked the native file picker")
                self.stage = 2
                self.js("location.href = '/?view=simple'")
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.waitForImport() }
            }
        }
    }

    func verifyDownload() {
        check(save, "WebKit invoked native save destination")
        let file = folder.appendingPathComponent("native-export.txt")
        check((try? String(contentsOf: file, encoding: .utf8)) == "EZNest native export", "saved exact download bytes")
        app.webView.takeSnapshot(with: nil) { image, error in
            self.check(error == nil && image != nil, "native WebKit screenshot")
            if let data = image?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: data),
               let png = bitmap.representation(using: .png, properties: [:]) {
                try? png.write(to: self.folder.appendingPathComponent("native-window.png"))
            }
            self.complete(["nativeWindow": true, "reopen": true, "modeNavigation": true,
                           "filePicker": self.picker, "downloadSaved": self.save,
                           "noBrowserOnStartup": true, "externalNavigationClosed": true])
        }
    }

    func complete(_ checks: [String: Bool]) {
        guard !finished else { return }
        finished = true
        let receipt: [String: Any] = ["mode": mode, "checks": checks]
        do {
            let data = try JSONSerialization.data(withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: folder.appendingPathComponent("receipt.json"))
        } catch { check(false, "write verification receipt") }
        print("NATIVE_PASS: \(mode)")
        NSApp.terminate(nil)
    }
}

@main struct NativeVerifier {
    @MainActor static func main() {
        let args = CommandLine.arguments
        guard (5...6).contains(args.count), let origin = URL(string: args[1]), let pid = Int(args[2]) else { exit(2) }
        if args[4] == "workspace", args.count == 6 {
            NativeWorkspaceChecks.run(origin: origin, pid: pid, folder: URL(fileURLWithPath: args[3]), version: args[5])
            return
        }
        let checks = DesktopChecks(origin: origin, pid: pid, folder: URL(fileURLWithPath: args[3]), mode: args[4])
        let app = NSApplication.shared
        app.delegate = checks.app
        app.setActivationPolicy(.regular)
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { checks.check(false, "native UI timeout") }
        app.run()
        withExtendedLifetime(checks) {}
    }
}
