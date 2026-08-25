import SwiftUI

/// The screens the Settings list opens. Every one performs its own server calls or says
/// plainly that it is read-only here; Organisation alone opens on the web.
enum SettingsDestination: String, CaseIterable, Identifiable, Hashable {
    case look
    case approvals
    case spending
    case health
    case archived
    case security
    case organisation
    case deleteAccount

    var id: String { rawValue }

    var label: String {
        switch self {
        case .look: return "Look"
        case .approvals: return "Approvals"
        case .spending: return "Spending"
        case .health: return "Health"
        case .archived: return "Archived chats"
        case .security: return "Security"
        case .organisation: return "Organisation"
        case .deleteAccount: return "Delete account"
        }
    }

    /// What the search box matches besides the label.
    var lead: String {
        switch self {
        case .look: return "Theme, density, text size, motion, contrast, and replies read out loud."
        case .approvals: return "What Boltrig asks before it acts."
        case .spending: return "What work has cost, and the ceilings on it."
        case .health: return "What is working, and what is not."
        case .archived: return "Closed chats, and bringing them back."
        case .security: return "Signed-in sessions and the keys for this account."
        case .organisation: return "People, keys and the record. Admin-only."
        case .deleteAccount: return "Remove your account from Boltrig."
        }
    }

    static func matching(_ query: String) -> [SettingsDestination] {
        let value = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return allCases }
        return allCases.filter {
            $0.label.localizedCaseInsensitiveContains(value) || $0.lead.localizedCaseInsensitiveContains(value)
        }
    }
}

/// A read or write that failed, shown at the top of the screen it belongs to.
struct SettingsNoticeSection: View {
    let message: String?

    var body: some View {
        if let message {
            Section {
                NoticeBanner(message: message, symbol: "exclamationmark.triangle.fill")
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }
        }
    }
}

/// A row with a title, a secondary line and a trailing action.
struct SettingsActionRow: View {
    let title: String
    let detail: String
    var tag: String?
    let action: String
    var destructive = false
    var disabled = false
    let perform: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(title)
                        .lineLimit(2)
                    if let tag {
                        Text(tag)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(BoltrigTheme.accent)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 2)
                            .background(BoltrigTheme.accent.opacity(0.14), in: Capsule())
                    }
                }
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button(action, role: destructive ? .destructive : nil, action: perform)
                .buttonStyle(.borderless)
                .disabled(disabled)
        }
        .padding(.vertical, 2)
    }
}

/// A quiet row for a list that has nothing in it yet.
struct SettingsEmptyRow: View {
    let text: String

    var body: some View {
        Text(text)
            .foregroundStyle(.secondary)
    }
}
