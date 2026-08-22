import Combine
import Foundation

/// The signed-in workspace: what needs the person, what is working, and the open chat.
/// Reads and writes go through one `BoltrigClient`; nothing here is inferred client-side
/// when the server states it.
@MainActor
final class AppStore: ObservableObject {
    @Published var selectedTab: AppTab = .today
    @Published private(set) var conversations: [ConversationSummary] = []
    @Published private(set) var approvals: [ApprovalRequest] = []
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var liveReply: String = ""
    @Published var selectedConversationID: String?
    @Published private(set) var isLoading = false
    @Published private(set) var isSending = false
    @Published private(set) var busyApprovalID: String?
    @Published var notice: String?
    @Published private(set) var loadError: String?
    @Published private(set) var needsYouDuringTurn = false

    let account: Account
    let isPreview: Bool
    private let client: BoltrigClient?
    private var loadedOnce = false
    private var activeTurn: Task<Void, Never>?

    init(client: BoltrigClient, account: Account) {
        self.client = client
        self.account = account
        self.isPreview = false
    }

    #if DEBUG
    /// Sample data for SwiftUI previews and the debug-only preview workspace.
    static func preview() -> AppStore {
        let store = AppStore(previewAccount: Account.preview)
        store.conversations = ConversationSummary.preview
        store.approvals = ApprovalRequest.preview
        store.messages = ChatMessage.preview
        return store
    }

    private init(previewAccount: Account) {
        self.client = nil
        self.account = previewAccount
        self.isPreview = true
    }
    #endif

    var selectedConversationTitle: String {
        guard let selectedConversationID,
              let conversation = conversations.first(where: { $0.id == selectedConversationID }) else {
            return "Boltrig"
        }
        return conversation.title
    }

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
        if selectedConversationID != conversation.id {
            selectedConversationID = conversation.id
            messages = []
            liveReply = ""
        }
        selectedTab = .chat
    }

    func startNewChat() {
        activeTurn?.cancel()
        selectedConversationID = nil
        messages = []
        liveReply = ""
        needsYouDuringTurn = false
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

    // MARK: Chat

    func sendMessage(_ value: String) async {
        let message = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !isSending else { return }
        messages.append(ChatMessage(role: .user, content: message, createdAt: Date()))
        needsYouDuringTurn = false
        guard let client else {
            isSending = true
            try? await Task.sleep(nanoseconds: 650_000_000)
            messages.append(ChatMessage(role: .assistant,
                                        content: "This is the preview workspace, so nothing was sent. Sign in to put Boltrig to work.",
                                        createdAt: Date()))
            isSending = false
            return
        }
        isSending = true
        liveReply = ""
        let stream = client.streamChat(message: message, conversationID: selectedConversationID, idempotencyKey: UUID().uuidString)
        let turn = Task { [weak self] in
            guard let self else { return }
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    self.apply(event)
                }
                self.finishTurn(reason: nil)
            } catch {
                let copy = (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription
                self.finishTurn(reason: copy)
            }
        }
        activeTurn = turn
        await turn.value
    }

    func stopTurn() {
        activeTurn?.cancel()
        finishTurn(reason: nil)
    }

    private func apply(_ event: ChatEvent) {
        switch event {
        case let .queued(conversationID):
            if let conversationID { selectedConversationID = conversationID }
            notice = "That went to the back of the queue. Boltrig will pick it up when the current step is done."
        case let .messageStart(_, conversationID):
            if !conversationID.isEmpty { selectedConversationID = conversationID }
        case let .textDelta(delta, degraded):
            liveReply += delta
            if degraded { notice = "Boltrig had to finish that turn without everything it wanted. The log has the detail." }
        case .needsYou, .question:
            needsYouDuringTurn = true
        case .messageEnd, .cancelled:
            break
        case .toolCall, .toolResult, .reasoningDelta, .heartbeat, .other:
            break
        }
    }

    private func finishTurn(reason: String?) {
        let reply = liveReply.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reply.isEmpty {
            messages.append(ChatMessage(role: .assistant, content: reply, createdAt: Date()))
        } else if let reason {
            messages.append(ChatMessage(role: .assistant, content: reason, createdAt: Date()))
        }
        liveReply = ""
        isSending = false
        activeTurn = nil
        if needsYouDuringTurn {
            Task { await refresh() }
        }
    }
}
