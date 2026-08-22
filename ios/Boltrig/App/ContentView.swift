import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: AppStore
    /// Set only for the debug preview workspace; hands control back to the sign-in screen.
    let onLeavePreview: (() -> Void)?

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
        .task {
            await store.loadIfNeeded()
        }
    }
}
