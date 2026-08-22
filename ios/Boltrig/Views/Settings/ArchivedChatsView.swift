import SwiftUI

/// Archived chats: the conversations that have been closed. Out of the way, not gone;
/// each can be brought back, and Today is refreshed once it is.
struct ArchivedChatsView: View {
    @EnvironmentObject private var settings: AccountSettingsStore
    @EnvironmentObject private var store: AppStore

    var body: some View {
        List {
            SettingsNoticeSection(message: settings.notice)

            if settings.archived.isEmpty {
                Section {
                    if settings.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .listRowBackground(Color.clear)
                    } else {
                        ContentUnavailableView(
                            "Nothing is archived",
                            systemImage: "archivebox",
                            description: Text("Closed chats land here, and can be brought back.")
                        )
                        .listRowBackground(Color.clear)
                    }
                }
            } else {
                Section {
                    ForEach(settings.archived) { chat in
                        SettingsActionRow(
                            title: chat.title,
                            detail: Self.activityLabel(chat.updatedAt),
                            action: settings.busyID == chat.id ? "Bringing back" : "Bring back",
                            disabled: settings.busyID != nil
                        ) {
                            Task {
                                if await settings.restore(id: chat.id) { await store.refresh() }
                            }
                        }
                    }
                } footer: {
                    Text("Dates show each chat's last activity.")
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Archived chats")
        .navigationBarTitleDisplayMode(.large)
        .task { await settings.loadArchived() }
        .refreshable { await settings.loadArchived() }
    }

    static func activityLabel(_ updatedAt: String) -> String {
        let age = updatedAt.relativeAge
        if age.isEmpty { return "Last activity unknown" }
        return age == "now" ? "Last activity just now" : "Last activity \(age) ago"
    }
}
