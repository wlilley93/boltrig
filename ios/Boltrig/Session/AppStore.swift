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
    @Published private(set) var devices: [LinkedDevice] = []
    @Published private(set) var isLoading = false
    @Published private(set) var busyApprovalID: String?
    @Published var notice: String?
    @Published private(set) var loadError: String?

    let account: Account
    let isPreview: Bool
    let chat: ChatSession
    let speaker: ReplySpeaker
    private let client: BoltrigClient?
    private var loadedOnce = false
    private var needsYouObserver: NSObjectProtocol?
    private var speechSinks: Set<AnyCancellable> = []

    init(client: BoltrigClient, account: Account, player: AudioPlaying = SystemAudioPlayer()) {
        self.client = client
        self.account = account
        self.isPreview = false
        self.chat = ChatSession(client: client)
        self.speaker = ReplySpeaker(client: client, player: player)
        observeNeedsYou()
        wireSpeech()
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
        self.speaker = ReplySpeaker(client: nil, player: SystemAudioPlayer())
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
        await resolveSpeech()
    }

    /// Reads which voice provider is bound and whether replies are read aloud.
    func resolveSpeech() async {
        guard let client else { return }
        let capabilities = try? await client.capabilities()
        speaker.resolution = SpeechResolution.resolve(account: account, capabilities: capabilities)
    }

    private func wireSpeech() {
        chat.speaker = speaker
        chat.setTurnEndedHandler { [weak self] text, runID in
            guard let self else { return }
            Task { await self.speaker.speak(runID: runID ?? UUID().uuidString, markdown: text) }
        }
        speaker.$isSpeaking.sink { [weak self] value in self?.chat.speaking = value }.store(in: &speechSinks)
        speaker.$level.sink { [weak self] value in self?.chat.speakingLevel = value }.store(in: &speechSinks)
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
            // The linked computers are shown when known; not knowing is not an error here.
            if let linked = try? await client.devices() { devices = linked.filter { $0.revokedAt == nil } }
        } catch {
            loadError = (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription
        }
    }

    /// Disconnects a computer from this account and drops it from the list.
    func disconnect(_ device: LinkedDevice) async {
        guard let client else {
            devices.removeAll { $0.id == device.id }
            return
        }
        do {
            try await client.revokeDevice(id: device.id)
            devices.removeAll { $0.id == device.id }
        } catch {
            notice = (error as? BoltrigError)?.errorDescription ?? error.localizedDescription
        }
    }

    var onlineDevice: LinkedDevice? { devices.first { $0.isOn() } }

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
