import Combine
import Foundation
import OSLog
import WebKit

/// Owns the one web view that runs Familiar's shader (the island) and the narrow message
/// channel to it. One surface hosts the island at a time; every other surface shows the
/// badge. When the island is missing from the bundle, or it reports that WebGL is
/// unavailable, the presence views fall back to the badge and nothing is ever blank.
@MainActor
final class FamiliarIslandController: NSObject, ObservableObject {
    @Published private(set) var isReady = false
    @Published private(set) var isFallback = false
    @Published private(set) var isAvailable = true
    @Published private(set) var owner: String?
    @Published private(set) var lastFrameRate: Double = 0
    @Published private(set) var lastError: String?

    private(set) lazy var webView: WKWebView = makeWebView()
    private(set) var reports: [String] = []
    /// Where Familiar's inner life is read from while a surface shows her; nil means she wanders.
    var phenotypeSource: BoltrigClient? {
        didSet { restartPhenotypePoll() }
    }
    @Published private(set) var phenotype: [String: Double]?
    private var phenotypePoll: Task<Void, Never>?
    private var sceneActive = true
    static let phenotypeInterval: TimeInterval = 3
    private var pending: FamiliarIslandState?
    private var lastSentJSON: String?
    private var flushScheduled = false
    private static let sendInterval: TimeInterval = 1.0 / 30.0

    static let messageName = "familiar"
    private static let log = Logger(subsystem: "ai.boltrig.app", category: "familiar-island")

    /// A surface asks to host the island. Only one may at a time. The first claim starts the
    /// page loading; the web view is created on demand, never before a surface wants it.
    func claim(_ surface: String) -> Bool {
        if owner == nil || owner == surface {
            let fresh = owner == nil
            owner = surface
            _ = webView
            if fresh { restartPhenotypePoll() }
            return true
        }
        return false
    }

    func release(_ surface: String) {
        if owner == surface {
            owner = nil
            apply(FamiliarIslandState(presentation: .minimised))
            restartPhenotypePoll()
        }
    }

    /// The presence views tell the controller whether the scene is active; the poll runs only then.
    func setSceneActive(_ active: Bool) {
        guard sceneActive != active else { return }
        sceneActive = active
        restartPhenotypePoll()
    }

    /// Polls the server's projection every few seconds while someone is looking; a stale or
    /// missing reading hands `nil` to the island, which then wanders on its own.
    private func restartPhenotypePoll() {
        phenotypePoll?.cancel()
        phenotypePoll = nil
        guard let client = phenotypeSource, owner != nil, sceneActive else {
            phenotype = nil
            return
        }
        phenotypePoll = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let reading = try? await client.familiarPhenotype()
                self.phenotype = reading?.values
                try? await Task.sleep(nanoseconds: UInt64(Self.phenotypeInterval * 1_000_000_000))
            }
        }
    }

    /// Queues a state for the island; sends at most thirty times a second, and only once
    /// the island has said it is ready.
    func apply(_ state: FamiliarIslandState) {
        pending = state
        guard isReady, !flushScheduled else { return }
        flushScheduled = true
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Self.sendInterval * 1_000_000_000))
            self?.flush()
        }
    }

    private func flush() {
        flushScheduled = false
        guard isReady, let state = pending else { return }
        pending = nil
        guard let json = try? state.json(), json != lastSentJSON else { return }
        lastSentJSON = json
        webView.callAsyncJavaScript(
            "if (window.familiarIsland) { window.familiarIsland.applyJSON(json); }",
            arguments: ["json": json],
            in: nil,
            in: .page
        ) { _ in }
    }

    private func makeWebView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.suppressesIncrementalRendering = true
        configuration.userContentController.add(WeakScriptMessageHandler(self), name: Self.messageName)
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isOpaque = false
        view.backgroundColor = .clear
        view.scrollView.backgroundColor = .clear
        view.scrollView.isScrollEnabled = false
        view.isUserInteractionEnabled = false
        view.navigationDelegate = self
        view.accessibilityElementsHidden = true
        if let url = Bundle.main.url(forResource: "familiar-island", withExtension: "html") {
            Self.log.info("island loading from bundle")
            view.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        } else {
            Self.log.error("island page missing from the bundle; badge only")
            isAvailable = false
        }
        return view
    }

    fileprivate func receive(_ message: Any) {
        guard let report = FamiliarIslandReport(message: message) else { return }
        reports.append(String(describing: report))
        if reports.count > 20 { reports.removeFirst() }
        Self.log.info("island report: \(String(describing: report), privacy: .public)")
        switch report {
        case .ready:
            isReady = true
            if pending != nil { apply(pending!) }
        case let .fallback(reason):
            isFallback = true
            lastError = reason
        case let .frame(fps, _):
            lastFrameRate = fps
        case let .error(message):
            lastError = message
        case .unknown:
            break
        }
    }
}

extension FamiliarIslandController: WKNavigationDelegate {
    nonisolated func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                             decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // Only the bundled page may load; nothing navigates away from it.
        if navigationAction.request.url?.isFileURL == true {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
        }
    }

    nonisolated func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        Task { @MainActor in
            Self.log.error("island navigation failed: \(error.localizedDescription, privacy: .public)")
            self.isFallback = true
            self.lastError = error.localizedDescription
        }
    }

    nonisolated func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        Task { @MainActor in
            Self.log.error("island provisional navigation failed: \(error.localizedDescription, privacy: .public)")
            self.isFallback = true
            self.lastError = error.localizedDescription
        }
    }

    nonisolated func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        Task { @MainActor in
            Self.log.info("island page loaded")
        }
    }

    nonisolated func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        Task { @MainActor in
            Self.log.error("island content process ended; reloading")
            self.isReady = false
            webView.reload()
        }
    }
}

/// The content controller retains its handler strongly; this proxy keeps the controller weak.
private final class WeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: FamiliarIslandController?

    init(_ target: FamiliarIslandController) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        let body = message.body
        Task { @MainActor [weak target] in
            target?.receive(body)
        }
    }
}
