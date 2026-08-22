import Combine
import Foundation

/// The open conversation: its stored history, the live turn, the question Boltrig is asking,
/// and the continuity notices that keep the record honest. One per app; it follows whichever
/// conversation is open.
@MainActor
final class ChatSession: ObservableObject {
    struct PendingQuestion: Equatable {
        let id: String
        let prompt: String
        let choices: [String]
    }

    @Published private(set) var conversationID: String?
    @Published private(set) var title: String = "Boltrig"
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var liveReply: String = ""
    @Published private(set) var receipts: [String] = []
    @Published private(set) var isLoadingHistory = false
    @Published private(set) var isSending = false
    @Published private(set) var isReconnecting = false
    @Published private(set) var activeRunID: String?
    @Published private(set) var pendingQuestion: PendingQuestion?
    @Published private(set) var needsYouDuringTurn = false
    @Published private(set) var turnFailed = false
    @Published var notice: String?
    @Published private(set) var historyError: String?
    @Published private(set) var attachments: [ChatAttachment] = []
    @Published private(set) var limits = AttachmentLimits()
    /// The one line under the composer about attachments: a refusal, or a limit that was hit.
    @Published private(set) var attachmentNotice: String?
    static let attachmentsRejectedCopy = "Boltrig could not accept those files. Remove one and try again."
    static let attachmentsFootnote = "Only text files are read. Photos and other files are kept with the message."
    /// Driven by the speaker: Familiar is reading a reply aloud, and how loudly.
    @Published var speaking = false
    @Published var speakingLevel: Double = 0
    /// Set by the workspace; the session stops speech when the person moves on.
    weak var speaker: ReplySpeaker?

    let isPreview: Bool
    private let client: BoltrigClient?
    private var turn: Task<Void, Never>?
    private var followCursor = 0
    private var onTurnEnded: ((String, String?) -> Void)?

    init(client: BoltrigClient) {
        self.client = client
        self.isPreview = false
    }

    #if DEBUG
    static func preview() -> ChatSession {
        let session = ChatSession(preview: true)
        session.messages = ChatMessage.preview
        session.title = "Prepare the morning briefing"
        return session
    }

    private init(preview: Bool) {
        self.client = nil
        self.isPreview = preview
    }
    #endif

    /// What Familiar's body shows, by the same precedence the web uses.
    var presenceMode: FamiliarIslandState.Mode {
        FamiliarModeResolver.mode(failed: turnFailed, speaking: speaking, listening: false,
                                  streaming: (isSending || isReconnecting) && !liveReply.isEmpty,
                                  loading: (isSending || isReconnecting || isLoadingHistory) && liveReply.isEmpty)
    }

    /// Called with the finished reply text and the run it belongs to; the speaker hooks in here.
    func setTurnEndedHandler(_ handler: @escaping (String, String?) -> Void) {
        onTurnEnded = handler
    }

    // MARK: Opening and history

    func open(_ conversation: ConversationSummary) async {
        if conversationID != conversation.id {
            speaker?.reset()
            stopTurn(cancelOnServer: false)
            conversationID = conversation.id
            title = conversation.title
            messages = []
            liveReply = ""
            receipts = []
            pendingQuestion = nil
            needsYouDuringTurn = false
            turnFailed = false
            notice = nil
        }
        await loadHistory()
    }

    func startNew() {
        speaker?.reset()
        stopTurn(cancelOnServer: false)
        conversationID = nil
        title = "Boltrig"
        messages = []
        liveReply = ""
        receipts = []
        activeRunID = nil
        pendingQuestion = nil
        needsYouDuringTurn = false
        turnFailed = false
        historyError = nil
        notice = nil
        attachments = []
    }

    /// Loads the stored messages. A run the server still calls active is followed once; the
    /// reload that follows a reconnect never reconnects again, so a stale flag cannot loop.
    func loadHistory(followActiveRun: Bool = true) async {
        guard let client, let conversationID else { return }
        isLoadingHistory = true
        historyError = nil
        defer { isLoadingHistory = false }
        do {
            let history = try await client.conversation(id: conversationID)
            title = history.title.isEmpty ? title : history.title
            messages = history.messages
                .filter { $0.supersededBy == nil && $0.role != .other }
                .map { ChatMessage(id: UUID(), role: $0.role == .user ? .user : .assistant, content: $0.content, createdAt: Date()) }
            if followActiveRun {
                activeRunID = history.activeRunID
                if history.activeRunID != nil {
                    await reconnect(since: 0)
                }
            }
            // After a reconnect the follow outcome is the truth about what is live; a stale
            // active_run_id on the reloaded history is not allowed to resurrect a finished run.
        } catch {
            historyError = (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription
        }
    }

    func loadLimitsIfNeeded() async {
        guard let client else { return }
        if let fetched = try? await client.chatConfig() { limits = fetched }
    }

    // MARK: Live turns

    func sendMessage(_ value: String) async {
        let message = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !isSending else { return }
        messages.append(ChatMessage(role: .user, content: message, createdAt: Date()))
        speaker?.stop()
        needsYouDuringTurn = false
        turnFailed = false
        pendingQuestion = nil
        let sending = attachments
        attachments = []
        attachmentNotice = nil
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
        receipts = []
        let stream = client.streamChat(message: message, conversationID: conversationID, idempotencyKey: UUID().uuidString, attachments: sending)
        let task = Task { [weak self] in
            guard let self else { return }
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    self.apply(event)
                }
                self.finishTurn(reason: nil)
            } catch {
                var copy = (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription
                if (error as? BoltrigError)?.status == 413 { copy = Self.attachmentsRejectedCopy }
                self.finishTurn(reason: copy)
            }
        }
        turn = task
        await task.value
    }

    /// Picks up a run that is live on the server, from a cursor.
    func reconnect(since: Int) async {
        guard let client, let conversationID else { return }
        isReconnecting = true
        notice = "Picking up the live turn."
        liveReply = ""
        let stream = client.follow(conversationID: conversationID, since: since)
        let task = Task { [weak self] in
            guard let self else { return }
            do {
                for try await outcome in stream {
                    if Task.isCancelled { break }
                    switch outcome {
                    case .idle:
                        self.activeRunID = nil
                        self.notice = nil
                    case let .frame(frame):
                        self.followCursor = max(self.followCursor, frame.cursor)
                        if frame.replayTruncated {
                            self.notice = "Earlier live activity is not shown. The full record appears when the turn settles."
                        }
                        self.apply(frame.event)
                    }
                }
                self.finishReconnect()
            } catch {
                self.notice = nil
                self.finishReconnect()
            }
        }
        turn = task
        await task.value
        if self.notice == "Picking up the live turn." { self.notice = nil }
        await loadHistory(followActiveRun: false)
    }

    func reconnectIfRunning() async {
        guard activeRunID != nil, !isSending, !isReconnecting else { return }
        await reconnect(since: followCursor)
    }

    /// Stops following and asks the server to stop the run at its next step.
    func stopTurn(cancelOnServer: Bool = true) {
        if cancelOnServer { speaker?.stop() }
        turn?.cancel()
        turn = nil
        if cancelOnServer, let client, let runID = activeRunID {
            notice = "Stopping. Boltrig finishes the current step first."
            Task { try? await client.cancelRun(id: runID) }
        }
        finishTurn(reason: nil)
    }

    func answerQuestion(_ answer: String) async {
        guard let client, let question = pendingQuestion else { return }
        let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do {
            try await client.answerQuestion(id: question.id, answer: trimmed)
            pendingQuestion = nil
            messages.append(ChatMessage(role: .user, content: trimmed, createdAt: Date()))
        } catch {
            notice = (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription
        }
    }

    // MARK: Attachments

    func addAttachment(_ attachment: ChatAttachment) -> String? {
        if attachments.count >= limits.maxCount {
            return "You can add up to \(limits.maxCount) files to one message."
        }
        if attachment.data.count > limits.maxBytes {
            return "That file is too big to send here. The limit is \(Self.size(limits.maxBytes)) each."
        }
        let total = attachments.reduce(0) { $0 + $1.data.count } + attachment.data.count
        if total > limits.maxTotalBytes {
            return "Those files add up to more than \(Self.size(limits.maxTotalBytes)). Remove one and try again."
        }
        attachments.append(attachment)
        return nil
    }

    /// Takes what the importer produced: a ready file goes in within the limits, a refusal is shown.
    func attach(_ outcome: AttachmentImporter.Outcome) {
        switch outcome {
        case let .ready(attachment): attachmentNotice = addAttachment(attachment)
        case let .refused(reason): attachmentNotice = reason
        }
    }

    func removeAttachment(named name: String) {
        attachmentNotice = nil
        attachments.removeAll { $0.name == name }
    }

    nonisolated static func size(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .binary)
    }

    // MARK: Internals

    private func apply(_ event: ChatEvent) {
        switch event {
        case let .queued(id):
            if let id { conversationID = id }
            notice = "That went to the back of the queue. Boltrig will pick it up when the current step is done."
        case let .messageStart(runID, id):
            if !id.isEmpty { conversationID = id }
            if !runID.isEmpty { activeRunID = runID }
        case let .textDelta(delta, degraded):
            liveReply += delta
            if degraded { notice = "Boltrig had to finish that turn without everything it wanted. The log has the detail." }
        case let .needsYou(_, _, question, _):
            needsYouDuringTurn = true
            if let question, !question.isEmpty { receipts.append("Needs you: \(question)") }
        case let .question(id, prompt, choices):
            pendingQuestion = PendingQuestion(id: id, prompt: prompt, choices: choices)
        case let .toolCall(verb, _):
            if let verb, !verb.isEmpty { receipts.append("Using \(verb)") }
        case let .toolResult(verb, status):
            if let verb, !verb.isEmpty, let status, status != "ok" { receipts.append("\(verb) did not finish: \(status)") }
        case let .subagent(_, task, name):
            receipts.append("\(name ?? "A helper") is on: \(task)")
        case let .artifact(name, _, size):
            receipts.append("Created \(name) (\(Self.size(size)))")
        case let .artifactRejected(count):
            receipts.append(count == 1 ? "One file could not be kept." : "\(count) files could not be kept.")
        case .steerQueued:
            notice = "Your message is queued behind the current step."
        case .cancelled:
            notice = "Stopped."
        case .messageEnd, .steerConsumed, .reasoningDelta, .heartbeat, .subagentEnd,
             .modelRouting, .workflowStep, .workflowRun, .displayObject, .eventUnavailable, .other:
            break
        }
    }

    private func finishTurn(reason: String?) {
        let reply = liveReply.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reply.isEmpty {
            messages.append(ChatMessage(role: .assistant, content: reply, createdAt: Date()))
            onTurnEnded?(reply, activeRunID)
        } else if let reason {
            messages.append(ChatMessage(role: .assistant, content: reason, createdAt: Date()))
            turnFailed = true
        }
        liveReply = ""
        isSending = false
        turn = nil
        activeRunID = nil
        if needsYouDuringTurn {
            NotificationCenter.default.post(name: .boltrigNeedsYou, object: nil)
        }
    }

    private func finishReconnect() {
        let reply = liveReply.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reply.isEmpty {
            messages.append(ChatMessage(role: .assistant, content: reply, createdAt: Date()))
        }
        liveReply = ""
        isReconnecting = false
        turn = nil
        activeRunID = nil
    }
}

extension Notification.Name {
    /// A turn ended with something waiting for the person; Today should refresh.
    static let boltrigNeedsYou = Notification.Name("boltrig.needsYou")
}
