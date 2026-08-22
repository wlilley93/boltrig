import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var session: SessionStore
    /// Set only for the debug preview workspace; hands control back to the sign-in screen.
    let onLeavePreview: (() -> Void)?

    var body: some View {
        // The account settings store is built once per signed-in workspace from the session's
        // client; the preview workspace gets no client, so its screens show their empty states.
        SignedInTabs(
            onLeavePreview: onLeavePreview,
            accountSettings: AccountSettingsStore(client: store.isPreview ? nil : session.apiClient,
                                                  account: store.account, session: session)
        )
    }
}

private struct SignedInTabs: View {
    @EnvironmentObject private var store: AppStore
    @StateObject private var accountSettings: AccountSettingsStore
    let onLeavePreview: (() -> Void)?

    init(onLeavePreview: (() -> Void)?, accountSettings: @autoclosure @escaping () -> AccountSettingsStore) {
        self.onLeavePreview = onLeavePreview
        _accountSettings = StateObject(wrappedValue: accountSettings())
    }

    var body: some View {
        TabView(selection: $store.selectedTab) {
            TodayView()
                .tabItem { Label("Today", systemImage: "sun.max") }
                .tag(AppTab.today)

            ChatView()
                .tabItem { Label("Chat", systemImage: "bubble.left.and.bubble.right") }
                .tag(AppTab.chat)

            SettingsView(onLeavePreview: onLeavePreview)
                .tabItem { Label("Settings", systemImage: "gearshape") }
                .tag(AppTab.settings)
        }
        .tint(BoltrigTheme.accent)
        .environmentObject(accountSettings)
        .preferredColorScheme(accountSettings.appearance.theme.colorScheme)
        .task {
            // The speaker resolved "read out replies" from the account snapshot; the toggle in
            // Look hands it the new answer directly, provider and voice unchanged.
            accountSettings.onReadRepliesChanged = { [weak store] enabled in
                guard let store else { return }
                let current = store.speaker.resolution
                store.speaker.resolution = SpeechResolution(enabled: enabled, provider: current.provider, voiceID: current.voiceID)
            }
            await store.loadIfNeeded()
        }
    }
}

private extension AppearanceSettings.Theme {
    /// The account's theme applied to this phone; "system" leaves the choice to iOS.
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .dark: return .dark
        case .light: return .light
        }
    }
}
