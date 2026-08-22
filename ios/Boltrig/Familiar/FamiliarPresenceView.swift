import SwiftUI
import WebKit

/// Familiar as she appears on a surface: the living shader when this surface holds the
/// island and it is ready, the badge otherwise. Never blank.
struct FamiliarPresenceView: View {
    let surface: String
    var presentation: FamiliarIslandState.Presentation = .conversation
    var mode: FamiliarIslandState.Mode = .standby
    var level: Double = 0
    var size: CGFloat = 96

    @EnvironmentObject private var island: FamiliarIslandController
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var holdsIsland = false

    /// The web view must be in the view hierarchy to load and paint, so it is attached as
    /// soon as this surface holds the island and shown once the island says it is ready.
    private var hostsIsland: Bool {
        holdsIsland && island.isAvailable && !island.isFallback
    }

    private var showsIsland: Bool {
        hostsIsland && island.isReady
    }

    var body: some View {
        ZStack {
            if hostsIsland {
                IslandHostView(webView: island.webView)
                    .frame(width: size, height: size)
                    .clipShape(Circle())
                    .opacity(showsIsland ? 1 : 0)
                    .animation(.easeInOut(duration: 0.4), value: showsIsland)
            }
            if !showsIsland {
                FamiliarBadgeView(working: mode == .working || mode == .thinking, size: size)
            }
        }
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Familiar")
        .accessibilityValue(Self.label(for: mode))
        .onAppear {
            holdsIsland = island.claim(surface)
            push()
        }
        .onDisappear {
            if holdsIsland { island.release(surface) }
            holdsIsland = false
        }
        .onChange(of: mode) { _, _ in push() }
        .onChange(of: level) { _, _ in push() }
        .onChange(of: scenePhase) { _, phase in
            island.setSceneActive(phase == .active)
            push()
        }
        .onChange(of: island.isReady) { _, _ in push() }
        .onChange(of: island.phenotype) { _, _ in push() }
        .onChange(of: colorScheme) { _, _ in push() }
    }

    private func push() {
        guard holdsIsland else { return }
        let active = scenePhase == .active
        island.apply(FamiliarIslandState(
            mode: mode,
            level: level,
            presentation: active ? presentation : .minimised,
            reducedMotion: reduceMotion,
            appearance: colorScheme == .dark ? .dark : .light,
            dprCap: min(Double(UIScreen.main.scale), 2),
            phenotype: island.phenotype
        ))
    }

    static func label(for mode: FamiliarIslandState.Mode) -> String {
        switch mode {
        case .standby: return "resting"
        case .listening: return "listening"
        case .thinking: return "thinking"
        case .working: return "working"
        case .speaking: return "speaking"
        case .error: return "something went wrong"
        }
    }
}

/// Hosts the controller's one web view wherever the island is shown.
private struct IslandHostView: UIViewRepresentable {
    let webView: WKWebView

    func makeUIView(context: Context) -> UIView {
        let container = UIView()
        container.backgroundColor = .clear
        return container
    }

    func updateUIView(_ container: UIView, context: Context) {
        if webView.superview !== container {
            webView.removeFromSuperview()
            webView.frame = container.bounds
            webView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            container.addSubview(webView)
        }
    }
}
