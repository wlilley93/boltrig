import SwiftUI

struct TodayView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var accountSettings: AccountSettingsStore

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    header

                    if let device = store.devices.first {
                        HStack(spacing: 8) {
                            Image(systemName: "desktopcomputer")
                                .foregroundStyle(device.isOn() ? BoltrigTheme.accent : Color.secondary)
                            Text(device.isOn() ? "\(device.label) is on" : "\(device.label): \(device.statusLabel().lowercased())")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                            Spacer()
                        }
                        .accessibilityElement(children: .combine)
                    }

                    if let loadError = store.loadError {
                        NoticeBanner(message: loadError, symbol: "exclamationmark.triangle.fill")
                    }
                    if let notice = store.notice {
                        NoticeBanner(message: notice, symbol: "info.circle.fill")
                    }

                    if !store.approvals.isEmpty {
                        approvalSection
                    }

                    if let working = store.workingConversation {
                        conversationSection(title: "Working now", rows: [working], working: true)
                    }

                    if !store.earlierConversations.isEmpty {
                        conversationSection(title: "Earlier", rows: store.earlierConversations, working: false)
                    }

                    if store.approvals.isEmpty && store.conversations.isEmpty && !store.isLoading && store.loadError == nil {
                        ContentUnavailableView(
                            "Nothing is waiting",
                            systemImage: "checkmark.circle",
                            description: Text("Ask Boltrig to do something below.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 44)
                    }

                    if store.isLoading && store.conversations.isEmpty {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 44)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 100)
            }
            .background(BoltrigTheme.groupedBackground.ignoresSafeArea())
            .safeAreaInset(edge: .bottom) {
                askButton
                    .padding(.horizontal, 16)
                    .padding(.top, 7)
                    .padding(.bottom, 8)
                    .background(.ultraThinMaterial)
            }
            .refreshable {
                await store.refresh()
            }
        }
    }

    private var presenceMode: FamiliarIslandState.Mode {
        store.workingConversation == nil ? .standby : .working
    }

    private var header: some View {
        HStack(alignment: .bottom, spacing: 14) {
            FamiliarPresenceView(surface: "today", presentation: .conversation, mode: presenceMode, size: 64)
                .padding(.bottom, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text(store.isPreview ? "Preview workspace" : store.account.nameForDisplay)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Text("Today")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                    .tracking(-0.6)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button {
                store.selectedTab = .settings
            } label: {
                Text(store.account.initials)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(BoltrigTheme.onControl)
                    .frame(width: 34, height: 34)
                    .background(BoltrigTheme.control, in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Settings")
        }
    }

    private var approvalSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Needs you")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            VStack(spacing: 0) {
                ForEach(store.approvals) { approval in
                    approvalCard(approval)
                    if approval.id != store.approvals.last?.id {
                        Divider().padding(.leading, 18)
                    }
                }
            }
            .background(BoltrigTheme.card, in: RoundedRectangle(cornerRadius: 16))
        }
    }

    private func approvalCard(_ approval: ApprovalRequest) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(alignment: .top, spacing: 9) {
                StatusDot(color: .orange)
                    .padding(.top, 5)
                VStack(alignment: .leading, spacing: 5) {
                    Text(approval.heading)
                        .font(.body.weight(.semibold))
                    Text(approval.question)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(spacing: 10) {
                Button {
                    Task { await store.respond(to: approval, decision: "approve") }
                } label: {
                    Text("Approve").frame(maxWidth: .infinity).foregroundStyle(BoltrigTheme.onControl)
                }
                .buttonStyle(.borderedProminent)
                .tint(BoltrigTheme.control)

                Button {
                    Task { await store.respond(to: approval, decision: "decline") }
                } label: {
                    Text("Not now").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(.primary)
            }
            .disabled(store.busyApprovalID == approval.id)
        }
        .padding(18)
    }

    private func conversationSection(title: String, rows: [ConversationSummary], working: Bool) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            VStack(spacing: 0) {
                ForEach(rows) { conversation in
                    Button {
                        store.openConversation(conversation)
                    } label: {
                        HStack(spacing: 11) {
                            FamiliarBadgeView(working: working, size: 42, label: conversation.title)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(conversation.title)
                                    .font(.body)
                                    .foregroundStyle(working ? .primary : .secondary)
                                    .lineLimit(1)
                                Text(conversation.status)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)

                            if !working {
                                Text(conversation.updatedAt.relativeAge)
                                    .font(.footnote)
                                    .foregroundStyle(.tertiary)
                            }
                            Image(systemName: "chevron.right")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 13)
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        if !working {
                            Button("Archive", systemImage: "archivebox") { archive(conversation) }
                        }
                    }

                    if conversation.id != rows.last?.id {
                        Divider().padding(.leading, 69)
                    }
                }
            }
            .background(BoltrigTheme.card, in: RoundedRectangle(cornerRadius: 16))
        }
    }

    /// Soft-closes a chat; it moves to Settings, Archived chats, and can be brought back.
    private func archive(_ conversation: ConversationSummary) {
        Task {
            if await accountSettings.archive(id: conversation.id) {
                await store.refresh()
            } else {
                store.notice = accountSettings.notice
            }
        }
    }

    private var askButton: some View {
        Button {
            store.startNewChat()
        } label: {
            HStack(spacing: 10) {
                Text("Ask Boltrig to do something")
                    .font(.body)
                    .foregroundStyle(.secondary)
                Spacer()
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(BoltrigTheme.accent)
                    .frame(width: 38, height: 38)
            }
            .padding(.leading, 18)
            .padding(.trailing, 7)
            .frame(height: 52)
            .background(BoltrigTheme.card, in: Capsule())
        }
        .buttonStyle(.plain)
    }
}
