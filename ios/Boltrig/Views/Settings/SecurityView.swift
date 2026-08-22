import SwiftUI

/// Security: who is signed in on the web or the desktop, and the keys on this account.
/// Revoking this phone's own key signs the phone out.
struct SecurityView: View {
    @EnvironmentObject private var settings: AccountSettingsStore
    @State private var revokingSession: UserSession?
    @State private var revokingKey: AccessTokenView?

    var body: some View {
        List {
            SettingsNoticeSection(message: settings.notice)

            Section {
                if settings.sessions.isEmpty {
                    SettingsEmptyRow(text: settings.isLoading ? "Checking" : "Nothing is signed in on the web right now.")
                } else {
                    ForEach(settings.sessions) { session in
                        SettingsActionRow(
                            title: session.clientLabel,
                            detail: session.lastSeenLabel,
                            action: "Revoke",
                            destructive: true,
                            disabled: settings.busyID != nil
                        ) { revokingSession = session }
                    }
                }
            } header: {
                Text("Signed-in sessions")
            } footer: {
                Text("Sign-ins on the web and on your computer.")
            }

            Section {
                if settings.tokens.isEmpty {
                    SettingsEmptyRow(text: settings.isLoading ? "Checking" : "No keys are listed.")
                } else {
                    ForEach(settings.tokens) { key in
                        SettingsActionRow(
                            title: key.name,
                            detail: key.expiryLabel(),
                            tag: key.isThisPhone ? "This phone" : nil,
                            action: "Revoke",
                            destructive: true,
                            disabled: settings.busyID != nil
                        ) { revokingKey = key }
                    }
                }
            } header: {
                Text("Keys for this account")
            } footer: {
                Text("This phone does not use a web session. It has its own key, listed above.")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Security")
        .navigationBarTitleDisplayMode(.large)
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog(
            "Revoke this session?",
            isPresented: Binding(get: { revokingSession != nil }, set: { if !$0 { revokingSession = nil } }),
            titleVisibility: .visible
        ) {
            Button("Revoke", role: .destructive) {
                if let session = revokingSession { Task { await settings.revokeSession(id: session.id) } }
                revokingSession = nil
            }
            Button("Cancel", role: .cancel) { revokingSession = nil }
        } message: {
            Text("It will have to sign in again.")
        }
        .confirmationDialog(
            revokingKey?.isThisPhone == true ? "Revoke this phone's key?" : "Revoke this key?",
            isPresented: Binding(get: { revokingKey != nil }, set: { if !$0 { revokingKey = nil } }),
            titleVisibility: .visible
        ) {
            Button(revokingKey?.isThisPhone == true ? "Revoke and sign out" : "Revoke", role: .destructive) {
                if let key = revokingKey { Task { await settings.revokeToken(id: key.id) } }
                revokingKey = nil
            }
            Button("Cancel", role: .cancel) { revokingKey = nil }
        } message: {
            Text(revokingKey?.isThisPhone == true
                 ? "This phone signs in with that key. You will be signed out here and will have to sign in again."
                 : "Anything using that key will have to sign in again.")
        }
    }

    private func load() async {
        await settings.loadSessions()
        await settings.loadTokens()
    }
}
