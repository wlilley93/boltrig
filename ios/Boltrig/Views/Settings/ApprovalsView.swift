import SwiftUI

/// Approvals: the three postures the web offers, with the current one ticked. Read-only on
/// the phone, because the server only accepts a change from a person signed in on the web.
struct ApprovalsView: View {
    @EnvironmentObject private var settings: AccountSettingsStore

    var body: some View {
        List {
            SettingsNoticeSection(message: settings.notice)

            Section {
                ForEach(ApprovalPostureReading.Posture.allCases, id: \.self) { option in
                    let current = settings.posture?.posture == option
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(option.title)
                            Text(option.detail)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        if current {
                            Image(systemName: "checkmark")
                                .font(.body.weight(.semibold))
                                .foregroundStyle(BoltrigTheme.accent)
                                .padding(.top, 2)
                        }
                    }
                    .padding(.vertical, 4)
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(current ? .isSelected : [])
                }
                .disabled(true)
            } header: {
                Text("Before Boltrig acts")
            } footer: {
                Text("To change this, sign in on the web. A change needs you there in person.")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Approvals")
        .navigationBarTitleDisplayMode(.large)
        .task { await settings.loadPosture() }
        .refreshable { await settings.loadPosture() }
    }
}
