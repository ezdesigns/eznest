import AppKit
import WebKit

// The desktop client has no filesystem/JavaScript bridge and never starts a
// second engine. Only the already installed, PID-matched shop service is loaded.
struct DesktopConfiguration {
    let origin: URL
    let version: String
    let servicePID: () -> Int?

    static func installed() -> DesktopConfiguration? {
        let info = Bundle.main.infoDictionary ?? [:]
        guard info["EzNestShopService"] as? Bool == true,
              let version = info["EzNestVersion"] as? String else { return nil }
        return DesktopConfiguration(origin: URL(string: "http://127.0.0.1:8765")!,
                                    version: version, servicePID: installedPID)
    }

    static func installedPID() -> Int? {
        let process = Process(), output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = ["print", "system/io.jeezlabs.eznest"]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        // launchctl output can contain an operator credential. Parse only PID;
        // never display, persist or forward the command output.
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0,
              let text = String(data: data, encoding: .utf8) else { return nil }
        for line in text.components(separatedBy: .newlines) {
            let fields = line.split(whereSeparator: { $0.isWhitespace })
            if fields.count == 3, fields[0] == "pid", fields[1] == "=",
               let pid = Int(fields[2]), pid > 0 { return pid }
        }
        return nil
    }

    func contains(_ url: URL) -> Bool {
        url.scheme == origin.scheme && url.host == "127.0.0.1" &&
        url.port == origin.port && url.user == nil && url.password == nil
    }

    func contains(_ origin: WKSecurityOrigin) -> Bool {
        origin.protocol == self.origin.scheme && origin.host == "127.0.0.1" &&
        origin.port == self.origin.port
    }

    func accepts(_ session: [String: Any]) -> Bool {
        guard let expected = servicePID(), expected > 0 else { return false }
        return session["app"] as? String == "eznest" &&
            session["version"] as? String == version &&
            session["shopService"] as? Bool == true &&
            session["pid"] as? Int == expected
    }
}

final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

@MainActor
final class DesktopApp: NSObject, NSApplicationDelegate, WKNavigationDelegate,
                        WKUIDelegate, WKDownloadDelegate {
    let configuration: DesktopConfiguration?
    private(set) var window: NSWindow!
    private(set) var webView: WKWebView!
    private var downloads: [ObjectIdentifier: WKDownload] = [:]
    private var popups: [ObjectIdentifier: WKWebView] = [:]
    private var probe: URLSessionDataTask?
    private var network: URLSession!

    #if EZNEST_DESKTOP_TESTING
    var pickFiles: ((WKOpenPanelParameters) -> [URL]?)?
    var saveDownload: ((String) -> URL?)?
    var externalLink: ((URL) -> Void)?
    var loaded: (() -> Void)?
    var downloadFinished: (() -> Void)?
    var failed: ((String) -> Void)?
    #endif

    init(configuration: DesktopConfiguration?) {
        self.configuration = configuration
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let settings = URLSessionConfiguration.ephemeral
        settings.connectionProxyDictionary = [:]
        settings.timeoutIntervalForRequest = 3
        network = URLSession(configuration: settings, delegate: NoRedirects(), delegateQueue: nil)
        let preferences = WKWebViewConfiguration()
        preferences.applicationNameForUserAgent = "EZNestDesktop"
        preferences.preferences.javaScriptCanOpenWindowsAutomatically = false
        webView = WKWebView(frame: .zero, configuration: preferences)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "EZNest"
        window.minSize = NSSize(width: 960, height: 640)
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("EZNest.Workspace")
        window.center()
        installMenus()
        showWindow(nil)
        reloadWorkspace(nil)
    }

    private func installMenus() {
        let bar = NSMenu(), appItem = NSMenuItem(), editItem = NSMenuItem(), windowItem = NSMenuItem()
        bar.addItem(appItem); bar.addItem(editItem); bar.addItem(windowItem)
        let app = NSMenu(title: "EZNest")
        app.addItem(withTitle: "About EZNest", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Quit EZNest", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = app
        let edit = NSMenu(title: "Edit")
        for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"),
                                        ("Copy", "copy:", "c"), ("Paste", "paste:", "v"),
                                        ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        editItem.submenu = edit
        let windows = NSMenu(title: "Window")
        let show = windows.addItem(withTitle: "EZNest", action: #selector(showWindow(_:)), keyEquivalent: "1")
        show.target = self
        let reload = windows.addItem(withTitle: "Reload Workspace", action: #selector(reloadWorkspace(_:)), keyEquivalent: "r")
        reload.target = self
        windowItem.submenu = windows
        NSApp.mainMenu = bar
        NSApp.windowsMenu = windows
    }

    @objc func showWindow(_ sender: Any?) {
        window.deminiaturize(nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow(nil)
        return false
    }

    @objc func reloadWorkspace(_ sender: Any?) {
        probe?.cancel()
        guard let configuration else {
            showError("This application is missing its installed shop configuration.")
            return
        }
        showMessage("Opening your workspace…", retry: false)
        var request = URLRequest(url: configuration.origin.appendingPathComponent("api/session"))
        request.cachePolicy = .reloadIgnoringLocalCacheData
        probe = network.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self, error == nil,
                      let response = response as? HTTPURLResponse, response.statusCode == 200,
                      let data, data.count <= 16384,
                      let session = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      configuration.accepts(session) else {
                    self?.showError("The installed EZNest service is unavailable or does not match this app. Check the installation, then try again.")
                    return
                }
                self.window.contentView = self.webView
                self.webView.load(URLRequest(url: configuration.origin.appendingPathComponent("/")))
            }
        }
        probe?.resume()
    }

    private func showMessage(_ text: String, retry: Bool) {
        let view = NSView(frame: window.contentView?.bounds ?? .zero)
        let label = NSTextField(wrappingLabelWithString: text)
        label.font = .systemFont(ofSize: 18)
        label.alignment = .center
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -20),
            label.widthAnchor.constraint(lessThanOrEqualToConstant: 620)])
        if retry {
            let button = NSButton(title: "Try Again", target: self, action: #selector(reloadWorkspace(_:)))
            button.translatesAutoresizingMaskIntoConstraints = false
            view.addSubview(button)
            NSLayoutConstraint.activate([button.centerXAnchor.constraint(equalTo: view.centerXAnchor),
                button.topAnchor.constraint(equalTo: label.bottomAnchor, constant: 20)])
        }
        window.contentView = view
    }

    private func showError(_ text: String) {
        showMessage(text, retry: true)
        #if EZNEST_DESKTOP_TESTING
        failed?(text)
        #endif
    }

    private func openExternal(_ url: URL) {
        guard url.scheme == "https", url.host != nil, url.user == nil, url.password == nil else { return }
        #if EZNEST_DESKTOP_TESTING
        externalLink?(url)
        #else
        NSWorkspace.shared.open(url)
        #endif
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let configuration, let url = action.request.url else { decisionHandler(.cancel); return }
        if popups[ObjectIdentifier(webView)] != nil {
            if url.absoluteString == "about:blank" {
                decisionHandler(.allow)
            } else {
                openExternal(url)
                decisionHandler(.cancel)
                popups.removeValue(forKey: ObjectIdentifier(webView))
            }
            return
        }
        let fromWorkspace = configuration.contains(action.sourceFrame.securityOrigin)
        if action.shouldPerformDownload && fromWorkspace &&
            (configuration.contains(url) || url.scheme == "blob") {
            decisionHandler(.download)
        } else if configuration.contains(url) {
            decisionHandler(.allow)
        } else {
            if fromWorkspace && action.navigationType == .linkActivated { openExternal(url) }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard let configuration, let url = response.response.url,
              configuration.contains(url) || url.scheme == "blob" else { decisionHandler(.cancel); return }
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // WebKit permits this only from a user gesture because automatic JS
        // windows are disabled. Preserve the blank handle across OUTPUT's async
        // checked-URL request; no external page is rendered in the app.
        guard let origin = self.configuration, origin.contains(action.sourceFrame.securityOrigin),
              popups.isEmpty else { return nil }
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        let popup = WKWebView(frame: .zero, configuration: configuration)
        popup.navigationDelegate = self
        popups[ObjectIdentifier(popup)] = popup
        return popup
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        guard webView === self.webView, configuration?.contains(frame.securityOrigin) == true else { completionHandler(nil); return }
        #if EZNEST_DESKTOP_TESTING
        if let pickFiles { completionHandler(pickFiles(parameters)); return }
        #endif
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { answer in completionHandler(answer == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        guard webView === self.webView, configuration?.contains(frame.securityOrigin) == true else { completionHandler(); return }
        let alert = NSAlert(); alert.messageText = "EZNest"; alert.informativeText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard webView === self.webView, configuration?.contains(frame.securityOrigin) == true else { completionHandler(false); return }
        let alert = NSAlert(); alert.messageText = "EZNest"; alert.informativeText = message
        alert.addButton(withTitle: "Continue"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { answer in completionHandler(answer == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { retain(download) }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { retain(download) }
    private func retain(_ download: WKDownload) { downloads[ObjectIdentifier(download)] = download; download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let name = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        #if EZNEST_DESKTOP_TESTING
        if let saveDownload { completionHandler(saveDownload(name)); return }
        #endif
        let panel = NSSavePanel()
        panel.nameFieldStringValue = name
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { answer in completionHandler(answer == .OK ? panel.url : nil) }
    }

    func downloadDidFinish(_ download: WKDownload) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
        #if EZNEST_DESKTOP_TESTING
        downloadFinished?()
        #endif
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
        if (error as NSError).code != NSURLErrorCancelled { showError("The file could not be saved. Please try again.") }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if EZNEST_DESKTOP_TESTING
        if webView === self.webView { loaded?() }
        #endif
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showError("The workspace could not be loaded. Please try again.") }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        guard urls.count == 1, urls[0].absoluteString == "eznest-update://install" else { return }
        // Preserve the existing separately authorized update request; no URLs,
        // paths or shell commands are forwarded from a page to the helper.
        let process = Process()
        process.executableURL = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/eznest")
        process.arguments = ["--request-macos-update"]
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { showError("The update request could not be opened.") }
    }
}

#if !EZNEST_DESKTOP_TESTING
@main
struct EZNestDesktop {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = DesktopApp(configuration: .installed())
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}
#endif
