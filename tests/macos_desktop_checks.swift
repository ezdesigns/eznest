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
            js("document.querySelector('#file').click()")
            waitForImport()
        } else if stage == 2 {
            check(app.webView.url?.query == "view=simple", "mode navigation stays in app")
            stage = 3
            js("document.querySelector('#bad').click(); document.querySelector('#external').click()")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                self.check(self.externalCount == 1, "only explicit HTTPS link leaves app")
                self.check(self.app.webView.url?.host == "127.0.0.1", "blocked external/file navigation")
                self.js("document.querySelector('#download').click()")
            }
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
        guard args.count == 5, let origin = URL(string: args[1]), let pid = Int(args[2]) else { exit(2) }
        let checks = DesktopChecks(origin: origin, pid: pid, folder: URL(fileURLWithPath: args[3]), mode: args[4])
        let app = NSApplication.shared
        app.delegate = checks.app
        app.setActivationPolicy(.regular)
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { checks.check(false, "native UI timeout") }
        app.run()
        withExtendedLifetime(checks) {}
    }
}
