import AppKit
import WebKit
import AVFoundation

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
final class DesktopStartupView: NSView {
    private let scene = NSView(), picture = NSImageView(), counterCover = NSView()
    private let rider: StartupRiderView
    private let ground = NSView(), label = NSTextField(labelWithString: "Loading")
    private let player: AVPlayer, movie = AVPlayerLayer()
    private var timer: Timer?, mediaStatus: NSKeyValueObservation?
    private var observers: [NSObjectProtocol] = []
    private var accessibilityObserver: NSObjectProtocol?, mediaObserver: NSObjectProtocol?
    private var last = ProcessInfo.processInfo.systemUptime, lastMedia = 0.0, stalled = 0.0
    private var ready = false, finished = false, posterOnly = false, ending = false
    private let completed: () -> Void, reducedMotion: () -> Bool
    private static let duration = 5.0, holdAt = 4.6
    private(set) var progress = 0.0
    private(set) var isHoldingForWorkspace = false, playbackCompleted = false
    var mediaIsDisplaying: Bool { !movie.isHidden && movie.isReadyForDisplay }
    var playbackTime: Double { let t = player.currentTime().seconds; return t.isFinite ? max(0, t) : 0 }
    let artworkLoaded: Bool
    override var isFlipped: Bool { true }
    private static let paper = NSColor(srgbRed: 247/255, green: 247/255, blue: 242/255, alpha: 1)

    init(frame: NSRect, reducedMotion: @escaping () -> Bool = { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }, completed: @escaping () -> Void) {
        let resources = Bundle.main.resourceURL ?? Bundle.main.bundleURL
        let poster = NSImage(contentsOf: resources.appendingPathComponent("startup-nesting-poster.png"))
        let companion = NSImage(contentsOf: resources.appendingPathComponent("startup-companion.png"))
        let url = resources.appendingPathComponent("startup-nesting.mp4")
        player = AVPlayer(url: url)
        self.rider = StartupRiderView(image: companion)
        self.artworkLoaded = poster != nil && companion != nil && FileManager.default.fileExists(atPath: url.path)
        self.completed = completed; self.reducedMotion = reducedMotion
        super.init(frame: frame)
        autoresizingMask = [.width, .height]
        wantsLayer = true; layer?.backgroundColor = Self.paper.cgColor
        scene.wantsLayer = true; scene.layer?.masksToBounds = true
        picture.image = poster; picture.imageScaling = .scaleAxesIndependently; picture.wantsLayer = true
        picture.setAccessibilityElement(false)
        player.isMuted = true; player.automaticallyWaitsToMinimizeStalling = false
        movie.player = player; movie.videoGravity = .resize; movie.isHidden = true
        picture.layer?.addSublayer(movie)
        counterCover.wantsLayer = true; counterCover.layer?.backgroundColor = Self.paper.cgColor
        scene.addSubview(picture); scene.addSubview(counterCover)
        ground.wantsLayer = true
        ground.layer?.backgroundColor = NSColor(srgbRed: 23/255, green: 33/255, blue: 52/255, alpha: 0.13).cgColor
        label.font = .systemFont(ofSize: 16, weight: .medium); label.alignment = .center
        label.textColor = NSColor(srgbRed: 23/255, green: 33/255, blue: 52/255, alpha: 1)
        label.setAccessibilityLabel("Loading")
        for item in [scene, ground, rider, label] { addSubview(item) }
        accessibilityObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil, queue: .main
        ) { [weak self] _ in MainActor.assumeIsolated { self?.updateMotion() } }
        mediaObserver = NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: player.currentItem, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.mediaEnded() }
        }
        mediaStatus = player.currentItem?.observe(\.status, options: [.initial, .new]) { [weak self] item, _ in
            if item.status == .failed { DispatchQueue.main.async { self?.usePoster() } }
        }
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers.removeAll()
        if let window {
            for name in [NSWindow.didMiniaturizeNotification, NSWindow.didDeminiaturizeNotification,
                         NSWindow.didChangeOcclusionStateNotification] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in MainActor.assumeIsolated { self?.updateMotion() } })
            }
            for name in [NSApplication.didHideNotification, NSApplication.didUnhideNotification] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in MainActor.assumeIsolated { self?.updateMotion() } })
            }
        }
        updateMotion()
    }

    override func layout() {
        super.layout()
        let width = min(680, max(0, bounds.width - 40)), sceneHeight = width * 470 / 800
        let height = sceneHeight + 105 - 8 + 23 + 20, top = (bounds.height - height) / 2
        scene.frame = NSRect(x: (bounds.width-width)/2, y: top, width: width, height: sceneHeight)
        // NSImageView's parent is not flipped: register the same cropped square
        // image and top-right counter cover used by the browser startup page.
        picture.frame = NSRect(x: 0, y: sceneHeight-width+width*0.22, width: width, height: width)
        movie.frame = picture.bounds
        counterCover.frame = NSRect(x: width*0.78, y: sceneHeight*0.87, width: width*0.22, height: sceneHeight*0.13)
        let laneWidth = min(300, width * 0.7), laneTop = top + sceneHeight - 8
        ground.frame = NSRect(x: (bounds.width-laneWidth)/2+12, y: laneTop+96, width: laneWidth-24, height: 2)
        rider.frame = NSRect(x: (bounds.width-laneWidth)/2+max(0,laneWidth-68)*progress, y: laneTop+4, width: 68, height: 95)
        label.frame = NSRect(x: (bounds.width-width)/2, y: laneTop+128, width: width, height: 20)
    }

    func markReady() { ready = true; updateMotion() }
    private func pause() { timer?.invalidate(); timer = nil; player.pause(); last = ProcessInfo.processInfo.systemUptime }
    private func usePoster() {
        guard !finished else { return }
        pause(); posterOnly = true; movie.isHidden = true
        mediaStatus?.invalidate(); mediaStatus = nil
        if let mediaObserver { NotificationCenter.default.removeObserver(mediaObserver) }; mediaObserver = nil
        movie.player = nil; player.replaceCurrentItem(with: nil)
        progress = ready ? 1 : 0.5; needsLayout = true
        if ready { complete() }
    }
    private func updateMotion() {
        guard !finished else { return }
        let reduced = reducedMotion()
        let visible = window?.isVisible == true && window?.isMiniaturized == false && !NSApp.isHidden
        if reduced || posterOnly {
            pause(); movie.isHidden = true; progress = ready ? 1 : 0.5; needsLayout = true
            if ready { complete() }; return
        }
        if !visible || (isHoldingForWorkspace && !ready) { pause(); return }
        if playbackCompleted { if ready { completeAfterFrame() }; return }
        if isHoldingForWorkspace { isHoldingForWorkspace = false; stalled = 0 }
        if timer == nil {
            last = ProcessInfo.processInfo.systemUptime
            timer = Timer(timeInterval: 1/60, repeats: true) { [weak self] _ in MainActor.assumeIsolated { self?.tick() } }
            RunLoop.main.add(timer!, forMode: .common)
        }
        player.play()
    }
    private func hold() {
        pause(); isHoldingForWorkspace = true
        if playbackTime > Self.holdAt + 0.05 { player.seek(to: CMTime(seconds: Self.holdAt, preferredTimescale: 37000), toleranceBefore: .zero, toleranceAfter: .zero) }
        progress = Self.holdAt / Self.duration; needsLayout = true
    }
    private func tick() {
        let now = ProcessInfo.processInfo.systemUptime, time = playbackTime
        stalled = time > lastMedia + 0.001 ? 0 : stalled + max(0, now-last)
        last = now; lastMedia = time
        movie.isHidden = !movie.isReadyForDisplay
        if !ready && time >= Self.holdAt { hold(); return }
        progress = min(1, time / Self.duration); needsLayout = true
        if stalled >= 8 { usePoster() }
    }
    private func mediaEnded() {
        guard !finished else { return }
        if !ready { hold(); return }
        pause(); playbackCompleted = true; completeAfterFrame()
    }
    private func completeAfterFrame() {
        guard !finished && !ending else { return }
        ending = true; progress = 1; needsLayout = true; layoutSubtreeIfNeeded()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1/60) { [weak self] in
            guard let self, !self.finished else { return }; self.complete()
        }
    }
    private func complete() { guard !finished else { return }; stop(); completed() }
    #if EZNEST_DESKTOP_TESTING
    func simulateStallForTesting() -> Bool {
        player.pause(); lastMedia = playbackTime
        last = ProcessInfo.processInfo.systemUptime - 8.1; tick()
        return posterOnly && player.currentItem == nil
    }
    #endif
    func stop() {
        finished = true; pause(); mediaStatus?.invalidate(); mediaStatus = nil
        for observer in observers { NotificationCenter.default.removeObserver(observer) }; observers.removeAll()
        if let mediaObserver { NotificationCenter.default.removeObserver(mediaObserver) }; mediaObserver = nil
        if let accessibilityObserver { NSWorkspace.shared.notificationCenter.removeObserver(accessibilityObserver) }; accessibilityObserver = nil
    }
}

@MainActor
private final class StartupRiderView: NSView {
    private let image: NSImage?
    override var isFlipped: Bool { true }
    init(image: NSImage?) { self.image = image; super.init(frame: .zero) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState(); context.translateBy(x: 68, y: 0); context.scaleBy(x: -1, y: 1)
        image?.draw(in: NSRect(x: 4, y: 17, width: 60, height: 72), from: .zero,
                    operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        context.translateBy(x: 0, y: 73); context.scaleBy(x: 68/56, y: 22/18)
        context.setStrokeColor(NSColor(srgbRed: 36/255, green: 39/255, blue: 39/255, alpha: 1).cgColor)
        context.setLineWidth(3); context.setLineCap(.round)
        context.move(to: CGPoint(x: 2, y: 5)); context.addQuadCurve(to: CGPoint(x: 13, y: 8), control: CGPoint(x: 7, y: 9))
        context.addLine(to: CGPoint(x: 44, y: 8)); context.addQuadCurve(to: CGPoint(x: 54, y: 3), control: CGPoint(x: 50, y: 8)); context.strokePath()
        context.setLineWidth(2)
        for (x, end) in [(14.0, 15.0), (42.0, 41.0)] { context.move(to: CGPoint(x: x, y: 9)); context.addLine(to: CGPoint(x: end, y: 14)) }; context.strokePath()
        context.setFillColor(NSColor(srgbRed: 52/255, green: 115/255, blue: 237/255, alpha: 1).cgColor); context.setLineWidth(1.4)
        for x in [15.0, 41.0] { context.addEllipse(in: CGRect(x: x-3, y: 11, width: 6, height: 6)); context.drawPath(using: .fillStroke) }
        context.restoreGState()
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
    private var startupView: DesktopStartupView?
    private var startupGeneration = 0
    private var startupNavigation: WKNavigation?
    private var startupAnimationFinished = false, startupPageLoaded = false

    #if EZNEST_DESKTOP_TESTING
    var pickFiles: ((WKOpenPanelParameters) -> [URL]?)?
    var saveDownload: ((String) -> URL?)?
    var externalLink: ((URL) -> Void)?
    var loaded: (() -> Void)?
    var downloadFinished: (() -> Void)?
    var failed: ((String) -> Void)?
    var popupCreated: (() -> Void)?
    var pendingPopupCount: Int { popups.count }
    var updateRequested: (() -> Void)?
    var startupShown: ((DesktopStartupView) -> Void)?
    var startupReducedMotion: (() -> Bool)?
    var startupIsVisible: Bool { startupView != nil }
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
        startupGeneration += 1
        let generation = startupGeneration
        probe?.cancel()
        webView.stopLoading()
        startupView?.stop(); startupView = nil; startupNavigation = nil
        startupAnimationFinished = false; startupPageLoaded = false
        guard let configuration else {
            showError("This application is missing its installed shop configuration.")
            return
        }
        #if EZNEST_DESKTOP_TESTING
        let motion = startupReducedMotion ?? { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
        #else
        let motion = { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
        #endif
        let loading = DesktopStartupView(frame: window.contentView?.bounds ?? .zero, reducedMotion: motion) { [weak self] in
            guard let self, self.startupGeneration == generation else { return }
            self.startupAnimationFinished = true; self.revealWorkspace()
        }
        startupView = loading; window.contentView = loading
        #if EZNEST_DESKTOP_TESTING
        startupShown?(loading)
        #endif
        var request = URLRequest(url: configuration.origin.appendingPathComponent("api/session"))
        request.cachePolicy = .reloadIgnoringLocalCacheData
        probe = network.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self, self.startupGeneration == generation else { return }
                guard error == nil,
                      let response = response as? HTTPURLResponse, response.statusCode == 200,
                      let data, data.count <= 16384,
                      let session = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      configuration.accepts(session) else {
                    self.showError("The installed EZNest service is unavailable or does not match this app. Check the installation, then try again.")
                    return
                }
                self.webView.frame = self.window.contentView?.bounds ?? .zero
                self.startupNavigation = self.webView.load(URLRequest(url: configuration.origin.appendingPathComponent("/")))
            }
        }
        probe?.resume()
    }

    private func revealWorkspace() {
        guard startupAnimationFinished && startupPageLoaded else { return }
        startupView?.stop(); startupView = nil; startupNavigation = nil
        window.contentView = webView
        window.makeFirstResponder(webView)
        #if EZNEST_DESKTOP_TESTING
        loaded?()
        #endif
    }

    private func waitForWorkspace(generation: Int, deadline: TimeInterval) {
        guard generation == startupGeneration, startupView != nil else { return }
        // Read presentation readiness only. This adds no JavaScript handler or
        // native capability; the service identity/origin gates remain above.
        webView.evaluateJavaScript("window.EZNStartup ? window.EZNStartup.state : 'ready'") { [weak self] value, error in
            guard let self, generation == self.startupGeneration, self.startupView != nil else { return }
            if value as? String == "failed" {
                self.startupAnimationFinished = true; self.revealWorkspace()
            } else if value as? String == "ready" {
                self.startupView?.markReady()
            } else if error != nil || ProcessInfo.processInfo.systemUptime >= deadline {
                self.showError("The workspace could not be loaded. Please try again.")
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                    self?.waitForWorkspace(generation: generation, deadline: deadline)
                }
            }
        }
    }

    private func showMessage(_ text: String, retry: Bool) {
        startupView?.stop(); startupView = nil; startupNavigation = nil
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

    func applicationWillTerminate(_ notification: Notification) {
        startupGeneration += 1; probe?.cancel(); startupView?.stop()
        network?.invalidateAndCancel()
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
        if webView === self.webView && fromWorkspace && action.sourceFrame.isMainFrame &&
            url.absoluteString == "eznest-update://install" {
            requestUpdate()
            decisionHandler(.cancel)
        } else if action.shouldPerformDownload && fromWorkspace &&
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
        popup.uiDelegate = self
        popups[ObjectIdentifier(popup)] = popup
        #if EZNEST_DESKTOP_TESTING
        popupCreated?()
        #endif
        return popup
    }

    func webViewDidClose(_ webView: WKWebView) {
        popups.removeValue(forKey: ObjectIdentifier(webView))
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
        if webView === self.webView, startupView != nil {
            guard startupNavigation === navigation else { return }
            startupPageLoaded = true
            waitForWorkspace(generation: startupGeneration, deadline: ProcessInfo.processInfo.systemUptime + 30)
            return
        }
        #if EZNEST_DESKTOP_TESTING
        if webView === self.webView { loaded?() }
        #endif
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if popups.removeValue(forKey: ObjectIdentifier(webView)) != nil { return }
        guard webView === self.webView else { return }
        guard startupView == nil || startupNavigation === navigation else { return }
        if (error as NSError).code != NSURLErrorCancelled { showError("The workspace could not be loaded. Please try again.") }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if popups.removeValue(forKey: ObjectIdentifier(webView)) != nil { return }
        guard startupView == nil || startupNavigation === navigation else { return }
        if webView === self.webView && (error as NSError).code != NSURLErrorCancelled {
            showError("The workspace could not be loaded. Please try again.")
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        guard urls.count == 1, urls[0].absoluteString == "eznest-update://install" else { return }
        requestUpdate()
    }

    private func requestUpdate() {
        #if EZNEST_DESKTOP_TESTING
        updateRequested?()
        return
        #else
        // Preserve the existing separately authorized update request; no URLs,
        // paths or shell commands are forwarded from a page to the helper.
        let process = Process()
        process.executableURL = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/eznest")
        process.arguments = ["--request-macos-update"]
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { showError("The update request could not be opened.") }
        #endif
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
