import Combine
import Foundation

/// The account's own settings and records: how Boltrig looks and speaks, what it asks
/// before acting, what has been archived, who is signed in, what it has cost, and what is
/// working. Writes are optimistic with a rollback; reads that fail say so in `notice`.
/// A nil client (the preview workspace) leaves every list empty and writes nothing.
@MainActor
final class AccountSettingsStore: ObservableObject {
    @Published private(set) var appearance: AppearanceSettings
    @Published private(set) var readReplies: Bool
    @Published private(set) var posture: ApprovalPostureReading?
    @Published private(set) var archived: [ConversationSummary] = []
    @Published private(set) var sessions: [UserSession] = []
    @Published private(set) var tokens: [AccessTokenView] = []
    @Published private(set) var budgets: [BudgetView] = []
    @Published private(set) var cost: CostSummary?
    @Published private(set) var readiness: ReadinessReport?
    @Published var notice: String?
    @Published private(set) var isLoading = false
    /// The row whose request is in flight: a chat being brought back, a session or key being revoked.
    @Published private(set) var busyID: String?
    /// Called once "read out replies" has been written, so the speaker follows at once
    /// instead of waiting for the account to be read again.
    var onReadRepliesChanged: ((Bool) -> Void)?

    private let client: BoltrigClient?
    private weak var session: SessionStore?

    init(client: BoltrigClient?, account: Account, session: SessionStore?) {
        self.client = client
        self.session = session
        self.appearance = account.appearance
        self.readReplies = account.readReplies
    }

    var isPreview: Bool { client == nil }

    // MARK: Look and voice

    /// Writes the five appearance keys together, as the web does, and rolls back on failure.
    func saveAppearance(_ value: AppearanceSettings) async {
        let previous = appearance
        appearance = value
        guard let client else { return }
        do {
            try await client.putSettings(value.wireForm)
            notice = nil
        } catch {
            appearance = previous
            notice = "Your appearance could not be saved."
        }
    }

    func setReadReplies(_ value: Bool) async {
        let previous = readReplies
        readReplies = value
        guard let client else { return }
        do {
            try await client.putSettings(["voice.read_replies": value])
            notice = nil
            onReadRepliesChanged?(value)
        } catch {
            readReplies = previous
            notice = "Read out replies could not be changed."
        }
    }

    // MARK: Approvals (read-only here)

    func loadPosture() async {
        await load { self.posture = try await $0.approvalPosture() }
    }

    // MARK: Archived chats

    /// Closed conversations, newest activity first.
    func loadArchived() async {
        await load {
            self.archived = try await $0.conversations()
                .filter { $0.status.lowercased() == "closed" }
                .sorted { $0.updatedAt > $1.updatedAt }
        }
    }

    /// Brings a closed chat back. The caller refreshes Today afterwards.
    @discardableResult
    func restore(id: String) async -> Bool {
        await act(on: id, unavailable: "Bringing chats back is not available in the preview workspace.") {
            try await $0.restoreConversation(id: id)
            self.archived.removeAll { $0.id == id }
        }
    }

    /// Soft-closes a chat; it lands in Archived chats and can be brought back.
    @discardableResult
    func archive(id: String) async -> Bool {
        await act(on: id, unavailable: "Archiving is not available in the preview workspace.") {
            try await $0.closeConversation(id: id)
        }
    }

    // MARK: Sessions and keys

    func loadSessions() async {
        await load { self.sessions = try await $0.sessions().filter { !$0.revoked } }
    }

    @discardableResult
    func revokeSession(id: String) async -> Bool {
        await act(on: id, unavailable: "Revoking is not available in the preview workspace.") {
            try await $0.revokeSession(id: id)
            self.sessions.removeAll { $0.id == id }
        }
    }

    /// Live keys, with the one this phone signs in with marked.
    func loadTokens() async {
        let phoneTokenID = session?.phoneTokenID
        await load {
            self.tokens = try await $0.tokens().filter { !$0.revoked }.map { token in
                var marked = token
                marked.isThisPhone = token.id == phoneTokenID
                return marked
            }
        }
    }

    /// Revoking this phone's own key signs the phone out; any other key is simply removed.
    @discardableResult
    func revokeToken(id: String) async -> Bool {
        if let session, id == session.phoneTokenID {
            await session.signOut()
            return true
        }
        return await act(on: id, unavailable: "Revoking is not available in the preview workspace.") {
            try await $0.revokeToken(id: id)
            self.tokens.removeAll { $0.id == id }
        }
    }

    // MARK: Spending and health

    func loadSpending() async {
        await load { client in
            async let budgets = client.budgets()
            async let cost = client.cost()
            let (rows, total) = try await (budgets, cost)
            self.budgets = rows
            self.cost = total
        }
    }

    func loadReadiness() async {
        await load { self.readiness = try await $0.readiness() }
    }

    // MARK: Account deletion

    /// Never reaches the network while `BoltrigEnvironment.accountDeletionAvailable` is false.
    func deleteAccount(password: String) async {
        guard BoltrigEnvironment.accountDeletionAvailable, let client else {
            notice = "Deleting your account from the app is not available yet. Ask support and it will be done for you."
            return
        }
        do {
            try await client.deleteAccount(password: password)
            await session?.signOut()
        } catch {
            notice = Self.copy(for: error)
        }
    }

    // MARK: Internals

    private func load(_ work: (BoltrigClient) async throws -> Void) async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            try await work(client)
            notice = nil
        } catch {
            notice = Self.copy(for: error)
        }
    }

    private func act(on id: String, unavailable: String, _ work: (BoltrigClient) async throws -> Void) async -> Bool {
        guard let client else {
            notice = unavailable
            return false
        }
        busyID = id
        defer { busyID = nil }
        do {
            try await work(client)
            notice = nil
            return true
        } catch {
            notice = Self.copy(for: error)
            return false
        }
    }

    private static func copy(for error: Error) -> String {
        (error as? BoltrigError)?.errorDescription ?? BoltrigError(kind: .unreachable, status: 0).errorDescription ?? ""
    }
}
