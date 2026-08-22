import SwiftUI

/// Delete account: what it removes, and the one button. The button stays off until the
/// server has a route for it (`BoltrigEnvironment.accountDeletionAvailable`).
struct DeleteAccountView: View {
    @EnvironmentObject private var settings: AccountSettingsStore
    @State private var confirming = false
    @State private var password = ""

    private var available: Bool { BoltrigEnvironment.accountDeletionAvailable }

    var body: some View {
        List {
            Section {
                Text("This removes your account, your conversations, your settings and your keys from Boltrig. Work that belongs to your organisation stays with it. This cannot be undone.")
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.vertical, 5)
            }

            Section {
                Button("Delete my account", role: .destructive) { confirming = true }
                    .disabled(!available)
            } footer: {
                if !available {
                    Text("Deleting your account from the app is not available yet. Ask support and it will be done for you.")
                }
            }

            SettingsNoticeSection(message: settings.notice)
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Delete your account")
        .navigationBarTitleDisplayMode(.large)
        .alert("Delete your account?", isPresented: $confirming) {
            SecureField("Your password", text: $password)
            Button("Delete my account", role: .destructive) {
                let entered = password
                password = ""
                Task { await settings.deleteAccount(password: entered) }
            }
            Button("Cancel", role: .cancel) { password = "" }
        } message: {
            Text("Enter your password to confirm. This cannot be undone.")
        }
    }
}
