import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var session: SessionStore
    @State private var query = ""
    @State private var confirmingSignOut = false
    @State private var disconnecting: LinkedDevice?
    let onLeavePreview: (() -> Void)?

    private var filteredItems: [SettingsDestination] {
        SettingsDestination.matching(query)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 14) {
                        Text(store.account.initials)
                            .font(.body.weight(.semibold))
                            .foregroundStyle(BoltrigTheme.onControl)
                            .frame(width: 44, height: 44)
                            .background(BoltrigTheme.control, in: Circle())

                        VStack(alignment: .leading, spacing: 2) {
                            Text(store.account.nameForDisplay)
                                .font(.body)
                            Text(store.account.email)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    .padding(.vertical, 4)

                    LabelValueRow(label: "Companion", value: "Familiar")
                    LabelValueRow(label: "Connected to", value: store.isPreview ? "Preview" : session.instanceLabel)
                    if let notice = session.familiarAdoptedNotice {
                        Text(notice)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Account")
                }

                Section {
                    if store.devices.isEmpty {
                        Text("No computer is linked yet.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(store.devices) { device in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(device.label)
                                    Text(device.statusLabel())
                                        .font(.subheadline)
                                        .foregroundStyle(device.isOn() ? BoltrigTheme.accent : Color.secondary)
                                }
                                Spacer()
                                Button("Disconnect", role: .destructive) { disconnecting = device }
                                    .buttonStyle(.borderless)
                            }
                        }
                    }
                    Link("Download Boltrig Desktop", destination: BoltrigEnvironment.desktopDownloadURL)
                } header: {
                    Text("Your computer")
                } footer: {
                    Text("Install Boltrig Desktop on your computer and sign in with this account. It then shows here, and this phone and that computer share one Boltrig.")
                }

                Section {
                    ForEach(filteredItems) { item in
                        NavigationLink(value: item) {
                            Text(item.label)
                        }
                    }
                } header: {
                    Text("Settings")
                }

                Section {
                    LabelValueRow(label: "Version", value: BoltrigEnvironment.versionLabel)
                    Link("Privacy policy", destination: BoltrigEnvironment.privacyPolicyURL)
                    Link("Terms", destination: BoltrigEnvironment.termsURL)
                    Link("Support", destination: BoltrigEnvironment.supportURL)
                } header: {
                    Text("About")
                }

                Section {
                    if let onLeavePreview {
                        Button("Leave the preview workspace") { onLeavePreview() }
                    } else {
                        Button("Sign out", role: .destructive) { confirmingSignOut = true }
                            .disabled(session.isBusy)
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Settings")
            .navigationDestination(for: SettingsDestination.self) { destination in
                destinationView(destination)
            }
            .searchable(text: $query, prompt: "Search every setting")
            .confirmationDialog("Sign out of Boltrig on this phone?", isPresented: $confirmingSignOut, titleVisibility: .visible) {
                Button("Sign out", role: .destructive) {
                    Task { await session.signOut() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Your work stays in Boltrig. This phone's access is revoked.")
            }
            .confirmationDialog("Disconnect \(disconnecting?.label ?? "this computer")?", isPresented: Binding(get: { disconnecting != nil }, set: { if !$0 { disconnecting = nil } }), titleVisibility: .visible) {
                Button("Disconnect", role: .destructive) {
                    if let device = disconnecting { Task { await store.disconnect(device) } }
                    disconnecting = nil
                }
                Button("Cancel", role: .cancel) { disconnecting = nil }
            } message: {
                Text("Boltrig Desktop on that computer will have to sign in again.")
            }
        }
    }
}

private extension SettingsView {
    @ViewBuilder
    func destinationView(_ destination: SettingsDestination) -> some View {
        switch destination {
        case .look: AppearanceView()
        case .approvals: ApprovalsView()
        case .spending: SpendingView()
        case .health: HealthView()
        case .archived: ArchivedChatsView()
        case .security: SecurityView()
        case .organisation: SettingDetailView(item: .organisation)
        case .deleteAccount: DeleteAccountView()
        }
    }
}

/// Organisation is managed on the web. The screen says so rather than showing
/// placeholder values; the link opens the signed-in instance.
private struct SettingDetailView: View {
    @EnvironmentObject private var session: SessionStore
    let item: SettingItem

    var body: some View {
        List {
            Section {
                Text(item.lead)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.vertical, 5)
            }

            Section {
                Link(destination: session.instanceURL) {
                    Label("Open \(item.title) on the web", systemImage: "safari")
                }
            } footer: {
                Text("These controls are not in the app yet. Changes made on the web apply here straight away.")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.large)
    }
}

private struct LabelValueRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
            Spacer()
            Text(value)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.trailing)
        }
    }
}
