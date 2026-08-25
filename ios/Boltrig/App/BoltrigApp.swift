import SwiftUI

@main
struct BoltrigApp: App {
    @StateObject private var session = SessionStore()
    @StateObject private var island = FamiliarIslandController()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(session)
                .environmentObject(island)
        }
    }
}

/// Where a signed-in account goes: first-run setup until the account records the web's
/// onboarding version, the workspace after.
enum RootDestination: Equatable {
    case workspace
    case onboarding

    static func resolve(_ account: Account) -> RootDestination {
        account.onboardingComplete ? .workspace : .onboarding
    }
}

/// Decides what the person sees from the session state alone. Nothing private renders
/// until the server has confirmed who is signed in.
struct RootView: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var island: FamiliarIslandController
    @State private var workspace: AppStore?
    @State private var onboarding: OnboardingStore?
    #if DEBUG
    @State private var previewWorkspace: AppStore?
    @State private var previewSetup: OnboardingStore?
    #endif

    var body: some View {
        Group {
            #if DEBUG
            if let previewSetup {
                OnboardingFlowView(store: previewSetup)
            } else if let previewWorkspace {
                ContentView(onLeavePreview: { self.previewWorkspace = nil })
                    .environmentObject(previewWorkspace)
            } else {
                sessionDriven
            }
            #else
            sessionDriven
            #endif
        }
        .task {
            #if DEBUG
            // Launch arguments for simulator captures: -boltrigPreview opens the preview
            // workspace without a session; -boltrigTab today|chat|settings picks the tab;
            // -boltrigOnboarding shows first-run setup against a stub, -boltrigStep picks the step.
            if CommandLine.arguments.contains("-boltrigOnboarding") {
                var step: String?
                if let index = CommandLine.arguments.firstIndex(of: "-boltrigStep"), index + 1 < CommandLine.arguments.count {
                    step = CommandLine.arguments[index + 1]
                }
                previewSetup = SetupPreview.store(step: step)
                return
            }
            if CommandLine.arguments.contains("-boltrigPreview") {
                let store = AppStore.preview()
                if let index = CommandLine.arguments.firstIndex(of: "-boltrigTab"), index + 1 < CommandLine.arguments.count {
                    switch CommandLine.arguments[index + 1] {
                    case "chat": store.selectedTab = .chat
                    case "settings": store.selectedTab = .settings
                    default: store.selectedTab = .today
                    }
                }
                if CommandLine.arguments.contains("-boltrigEmptyChat") { store.startNewChat() }
                previewWorkspace = store
                return
            }
            #endif
            await session.restore()
        }
    }

    @ViewBuilder
    private var sessionDriven: some View {
        switch session.state {
        case .restoring:
            LaunchView()
        case .unreachable:
            UnreachableView()
        case let .signedIn(account):
            switch RootDestination.resolve(account) {
            case .onboarding:
                if let onboarding {
                    OnboardingFlowView(store: onboarding)
                } else {
                    LaunchView()
                        .onAppear { makeOnboarding() }
                }
            case .workspace:
                if let workspace {
                    ContentView(onLeavePreview: nil)
                        .environmentObject(workspace)
                } else {
                    LaunchView()
                        .onAppear {
                            onboarding = nil
                            makeWorkspace()
                        }
                }
            }
        default:
            AuthFlowView(onExplorePreview: explorePreview)
                .onAppear {
                    workspace = nil
                    onboarding = nil
                    island.phenotypeSource = nil
                }
        }
    }

    private func makeWorkspace() {
        guard let client = session.apiClient, let account = session.account else { return }
        workspace = AppStore(client: client, account: account)
        island.phenotypeSource = client
    }

    /// First-run setup runs against the signed-in client; pressing Start re-reads the account,
    /// which flips the destination to the workspace.
    private func makeOnboarding() {
        guard let client = session.apiClient, let account = session.account else { return }
        let session = self.session
        let store = OnboardingStore(client: client, account: account)
        store.onFinished = { Task { await session.refreshAccount() } }
        onboarding = store
        island.phenotypeSource = client
    }

    private func explorePreview() {
        #if DEBUG
        previewWorkspace = AppStore.preview()
        #endif
    }
}

private struct LaunchView: View {
    var body: some View {
        VStack(spacing: 18) {
            BrandMark(size: 72)
            ProgressView()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
    }
}

private struct UnreachableView: View {
    @EnvironmentObject private var session: SessionStore

    var body: some View {
        VStack(spacing: 16) {
            BrandMark(size: 72)
            Text("Boltrig could not be reached")
                .font(.title3.weight(.semibold))
            Text("Check your connection, then try again. Your sign-in is kept.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button {
                Task { await session.retryRestore() }
            } label: {
                Text("Try again").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            Button("Sign in again") {
                Task { await session.signOut() }
            }
            .font(.subheadline)
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
    }
}
