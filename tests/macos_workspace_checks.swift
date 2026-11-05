import AppKit
import WebKit

// Actual EZNest pages/engine, hosted against scratch data by the Python runner.
// No installed service, production files or OUTPUT account is used here.
@MainActor final class NativeWorkspaceChecks {
    let app: DesktopApp
    let folder: URL
    var page = 0
    var picker = false
    var finished = false

    init(origin: URL, pid: Int, folder: URL, version: String) {
        self.folder = folder
        app = DesktopApp(configuration: DesktopConfiguration(origin: origin, version: version, servicePID: { pid }))
        app.startupReducedMotion = { false }
        app.failed = { [weak self] _ in self?.check(false, "workspace startup") }
        app.externalLink = { [weak self] _ in self?.check(false, "unexpected browser launch") }
        app.pickFiles = { [weak self] _ in
            self?.picker = true
            return [folder.appendingPathComponent("synthetic.svg")]
        }
        app.saveDownload = { [weak self] name in
            self?.check(name.hasSuffix(".zip"), "workspace print pack name")
            return folder.appendingPathComponent("workspace.zip")
        }
        app.downloadFinished = { [weak self] in self?.downloaded() }
        app.loaded = { [weak self] in self?.loaded() }
    }

    func check(_ okay: Bool, _ name: String) {
        if !okay { fputs("WORKSPACE_FAIL: \(name)\n", stderr); exit(1) }
    }

    func js(_ script: String, done: @escaping (Any?) -> Void = { _ in }) {
        app.webView.evaluateJavaScript(script) { value, error in
            self.check(error == nil, "native workspace JavaScript")
            done(value)
        }
    }

    func wait(_ condition: String, done: @escaping () -> Void) {
        js(condition) { value in
            if value as? Bool == true { done() }
            else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.wait(condition, done: done) } }
        }
    }

    func screenshot(_ filename: String, done: @escaping () -> Void) {
        app.webView.takeSnapshot(with: nil) { image, error in
            self.check(error == nil && image != nil, "workspace screenshot")
            guard let data = image?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: data),
                  let png = bitmap.representation(using: .png, properties: [:]) else {
                self.check(false, "workspace screenshot bytes"); return
            }
            do { try png.write(to: self.folder.appendingPathComponent(filename)) }
            catch { self.check(false, "write workspace screenshot") }
            done()
        }
    }

    func loaded() {
        if page == 0 {
            page = 1
            wait("document.body.dataset.ready === '1'") {
                print("WORKSPACE_STAGE: workspace-ready")
                self.js("window.location.href='/?view=full'")
            }
        } else if page == 1 {
            page = 2
            wait("document.body.dataset.ready === '1' && !document.querySelector('#mode-switch')") {
                print("WORKSPACE_STAGE: legacy-bookmark-loaded")
                self.js("document.querySelector('#stock-open').click()")
                self.wait("inventoryReady && document.querySelector('#stock').open") {
                    print("WORKSPACE_STAGE: legacy-bookmark-ready")
                    self.check(self.app.window.isVisible, "single workspace native window")
                    self.screenshot("full-workspace.png") {
                        self.js("document.querySelector('#stock-close').click(); window.location.href='/?view=simple'")
                    }
                }
            }
        } else if page == 2 {
            page = 3
            wait("document.body.dataset.ready === '1'") {
                print("WORKSPACE_STAGE: workspace-return-ready")
                self.js("""
                    const welcome = document.querySelector('#feedback-welcome');
                    if (welcome && welcome.getClientRects().length) document.querySelector('#feedback-dismiss').click();
                    document.querySelector('#edit-material').click();
                    """)
                self.wait("document.querySelector('#material-dialog').open") {
                    self.js("""
                        const unit=document.querySelector('#unit');unit.value='mm';unit.dispatchEvent(new Event('change',{bubbles:true}));
                        for(const [id,value] of [['preset-name','CI native stock'],['roll','110'],['width','100']]) {
                            const field=document.querySelector('#'+id);field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));
                        }
                        document.querySelector('#save-material').click();
                        """)
                    self.wait("!document.querySelector('#material-dialog').open") {
                        print("WORKSPACE_STAGE: material-saved")
                        self.js("document.querySelector('#nesting-effort').value='5'; document.querySelector('#file').click()")
                        self.wait("!document.querySelector('#start-nesting').disabled") {
                            print("WORKSPACE_STAGE: file-imported")
                            self.check(self.picker, "actual workspace native file input")
                            self.js("document.querySelector('#start-nesting').click()")
                            self.wait("/cuts ok/i.test(document.querySelector('#gate').textContent)") {
                                print("WORKSPACE_STAGE: nest-ready"); self.export()
                            }
                        }
                    }
                }
            }
        }
    }

    func export() {
        js("document.querySelector('#export').click()")
        wait("document.querySelector('#save-destination').getClientRects().length > 0") {
            print("WORKSPACE_STAGE: save-dialog")
            self.js("""
                for (const [id,value] of [['save-destination','download'],['save-format','pack']]) {
                    const field=document.querySelector('#'+id);field.value=value;field.dispatchEvent(new Event('change',{bubbles:true}));
                }
                document.querySelector('#confirm-send').click();
                """)
        }
    }

    func downloaded() {
        guard !finished else { return }
        finished = true
        let bytes = try? Data(contentsOf: folder.appendingPathComponent("workspace.zip"))
        check(bytes?.prefix(2) == Data([0x50, 0x4b]), "native saved ZIP bytes")
        screenshot("simple-workspace.png") {
            let receipt: [String: Any] = ["mode": "workspace", "checks": [
                "legacyFullLink": true, "singleWorkspace": true, "filePicker": self.picker,
                "nativePrintPackSaved": true, "noBrowserOnStartup": true]]
            do {
                let data = try JSONSerialization.data(withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys])
                try data.write(to: self.folder.appendingPathComponent("receipt.json"))
            } catch { self.check(false, "workspace receipt") }
            print("WORKSPACE_PASS: actual full/simple UI, SVG import, nesting and native ZIP save")
            NSApp.terminate(nil)
        }
    }

    static func run(origin: URL, pid: Int, folder: URL, version: String) {
        let checks = NativeWorkspaceChecks(origin: origin, pid: pid, folder: folder, version: version)
        let application = NSApplication.shared
        application.delegate = checks.app
        application.setActivationPolicy(.regular)
        DispatchQueue.main.asyncAfter(deadline: .now() + 100) { checks.check(false, "actual workspace timeout") }
        application.run()
        withExtendedLifetime(checks) {}
    }
}
