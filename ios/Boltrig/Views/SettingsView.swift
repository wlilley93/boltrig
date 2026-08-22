import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var session: SessionStore
    @State private var query = ""
    @State private var confirmingSignOut = false
    let onLeavePreview: (() -> Void)?

    private var filteredItems: [SettingItem] {
        let value = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return SettingItem.all }
        return SettingItem.all.filter {
            $0.label.localizedCaseInsensitiveContains(value)
                || $0.lead.localizedCaseInsensitiveContains(value)
        }
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

                    LabelValueRow(label: "Companion", value: store.account.companionName)
                    LabelValueRow(label: "Connected to", value: store.isPreview ? "Preview" : session.instanceLabel)
                    if !store.account.onboardingComplete && !store.isPreview {
                        Text("Finish setting up on the web to choose your companion and connect a provider.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Account")
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
            .navigationDestination(for: SettingItem.self) { item in
                SettingDetailView(item: item)
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
        }
    }
}

/// Each section is managed on the web for now. The screen says so rather than showing
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
