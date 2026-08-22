import Combine
import Foundation

/// The signed-in workspace: what needs the person and what is working. The open chat lives
/// in `ChatSession`. Reads and writes go through one `BoltrigClient`; nothing here is
/// inferred client-side when the server states it.
@MainActor
final class AppStore: ObservableObject {
    @Published var selectedTab: AppTab = .today
    @Published private(set) var conversations: [ConversationSummary] = []
    @Published private(set) var approvals: [ApprovalRequest] = []
    @Published private(set) var isLoading = false
    @Published private(set) var busyApprovalID: String?
    @Published var notice: String?
    @Published private(set) var loadError: String?

    let account: Account
    let isPreview: Bool
    let chat: ChatSession
    private let client: BoltrigClient?
    private var loadedOnce = false
    private var needsYouObserver: NSObjectProtocol?

    init(client: BoltrigClient, account: Account) {
        self.client = client
        self.account = account
        self.isPreview = false
        self.chat = ChatSession(client: client)
        observeNeedsYou()
    }

    #if DEBUG
    /// Sample data for SwiftUI previews and the debug-only preview workspace.
    static func preview() -> AppStore {
        let store = AppStore(previewAccount: Account.preview)
        store.conversations = ConversationSummary.preview
        store.approvals = ApprovalRequest.preview
        return store
    }

    private init(previewAccount: Account) {
        self.client = nil
        self.account = previewAccount
        self.isPreview = true
        self.chat = ChatSession.preview()
    }
    #endif

    var workingConversation: ConversationSummary? {
        conversations.first(where: { $0.isWorking })
    }

    var earlierConversations: [ConversationSummary] {
        conversations.filter { !$0.isWorking }
    }

    // MARK: Loading

    func loadIfNeeded() async {
        guard !loadedOnce else { return }
        loadedOnce = true
        await refresh()
        await chat.loadLimitsIfNeeded()
    }

    func refresh() async {
        guard let client else { return }
        isLoading = true
        loadError = nil
        defer { isLoading = false }
        do {
            async let liveApprovals = client.approvals()
            async let liveConversations = client.conversations()
            let (newApprovals, newConversations) = try await (liveApprovals, liveConversations)
            approvals = newApprovals
            conversations = newConversations.filter { $0.status.lowercased() != "closed" }
        } catch {
            loadError = (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription
        }
    }

    // MARK: Navigation

    func openConversation(_ conversation: ConversationSummary) {
        selectedTab = .chat
        Task { await chat.open(conversation) }
    }

    func startNewChat() {
        chat.startNew()
        selectedTab = .chat
    }

    // MARK: Approvals

    func respond(to approval: ApprovalRequest, decision: String) async {
        busyApprovalID = approval.id
        defer { busyApprovalID = nil }
        guard let client else {
            approvals.removeAll { $0.id == approval.id }
            notice = decision == "approve" ? "Approved in the preview workspace." : "Left for later in the preview workspace."
            return
        }
        do {
            try await client.respond(to: approval.id, decision: decision)
            approvals.removeAll { $0.id == approval.id }
            notice = nil
        } catch {
            notice = (error as? BoltrigError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func observeNeedsYou() {
        needsYouObserver = NotificationCenter.default.addObserver(forName: .boltrigNeedsYou, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in await self?.refresh() }
        }
    }
}
