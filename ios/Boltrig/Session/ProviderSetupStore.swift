import Combine
import Foundation

/// One provider intake: the text model on the Provider step, the optional image model on the
/// step after. Mirrors the web app's provider setup so the phone and the browser make the same
/// calls in the same order and say the same things. One press covers the whole journey: save,
/// answer the approval the server raised, bind, and read back whether the provider answers.
@MainActor
final class ProviderSetupStore: ObservableObject {
    static let adminRoles: Set<String> = ["admin", "org-admin", "owner", "superadmin"]

    enum Copy {
        static let incomplete = "Choose a provider, add its key and pick a model to continue."
        static let keyMissing = "Add your key to continue."
        static let waiting = "This connection is waiting for an administrator's approval."
        static let savedUnconfirmed = "Provider saved. We couldn't confirm it is reachable."
        static let savedNotAnswering = "Provider saved, but it did not answer. Check the address: a self-hosted server is usually http, not https. Then enter your key again and press Continue."
        static let connected = "Provider connected."
        static let managed = "Your organisation manages your AI."
        static let checking = "Checking your AI"
    }

    let modality: AIModality

    @Published private(set) var readiness: AIKeysReadiness?
    @Published private(set) var catalogue: ProviderCatalogue?
    @Published private(set) var isLoading = false
    @Published var provider = "openai"
    @Published var model = ""
    @Published var baseURL = ""
    /// Bound to the key field. Blanked the moment a submission is built, before anything is awaited.
    @Published var apiKey = ""
    @Published private(set) var proposal: AIKeyProposal?
    @Published private(set) var busy = false
    @Published var message = ""

    private let client: BoltrigClient
    private let account: Account

    init(client: BoltrigClient, account: Account, modality: AIModality, catalogue: ProviderCatalogue? = nil) {
        self.client = client
        self.account = account
        self.modality = modality
        self.catalogue = catalogue
    }

    // MARK: Derived state

    var isAdmin: Bool { Self.adminRoles.contains(account.role) }

    /// Whether this person may save a key here at all: their organisation allows own keys,
    /// or they administer it and save at the organisation level.
    var canAddKey: Bool {
        guard let readiness else { return false }
        return readiness.allowOwn || isAdmin
    }

    var level: String { readiness?.allowOwn == true ? "user" : "org" }

    var existingKey: AIKeyView? { readiness?.existingKey(userID: account.id, modality: modality) }

    /// The catalogue rules in force; the two rule-bearing entries until the file has loaded.
    var rules: ProviderCatalogue { catalogue ?? .minimal }

    var selectedProvider: CatalogueProvider? { rules.provider(provider) }

    var selectedModel: CatalogueModel? {
        selectedProvider?.models.first { ProviderCatalogue.exactModelID(provider: provider, model: $0.id) == model }
    }

    var keyOptional: Bool { rules.keyOptional(provider) }

    /// Whether the Address row is shown: a custom provider, a self-hosted server, or a
    /// provider the catalogue publishes no address for.
    var needsAddress: Bool { provider == "custom" || rules.needsBaseURL(provider) }

    /// The model as the person sees it in the "Model name" field: without the provider prefix.
    var typedModelName: String {
        let prefix = provider + "/"
        return model.hasPrefix(prefix) ? String(model.dropFirst(prefix.count)) : model
    }

    // MARK: Loading

    /// Reads the catalogue (once per launch) and the saved keys. A failed read leaves
    /// `readiness` nil with the reason in `message`; the step still lets the person through.
    func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        if catalogue == nil {
            catalogue = try? await ProviderCatalogue.shared()
        }
        do {
            readiness = try await client.aiKeys()
            message = ""
        } catch {
            readiness = nil
            message = Self.describe(error)
        }
    }

    func selectProvider(_ id: String) {
        guard id != provider else { return }
        provider = id
        model = ""
        if id != "custom" { baseURL = "" }
        message = ""
    }

    func setTypedModelName(_ name: String) {
        model = name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "" : ProviderCatalogue.exactModelID(provider: provider, model: name)
    }

    // MARK: One press

    /// Everything Continue does on this step. True means the step may advance.
    func complete() async -> Bool {
        if let proposal {
            return await approveAndConnect(proposal)
        }
        let typedModel = model.trimmingCharacters(in: .whitespacesAndNewlines)
        if apiKey.isEmpty && typedModel.isEmpty {
            if let existing = existingKey, existing.gatewayReady != true {
                return await activate(existing)
            }
            return true
        }
        let addressMissing = needsAddress && baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if typedModel.isEmpty || addressMissing {
            message = Copy.incomplete
            return false
        }
        if apiKey.isEmpty && !keyOptional {
            message = Copy.keyMissing
            return false
        }
        let trimmedProvider = provider.trimmingCharacters(in: .whitespacesAndNewlines)
        let typedAddress = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let submission = AIKeySubmission(
            level: level,
            provider: trimmedProvider,
            model: typedModel,
            modality: modality,
            // A typed address always wins; failing that, a non-native provider submits the
            // catalogue's published address, which the server needs to bind it.
            baseURL: typedAddress.isEmpty ? rules.publishedBaseURL(trimmedProvider) : typedAddress,
            apiKey: apiKey
        )
        // The key leaves the field before the first await: once it is sent, nothing on screen
        // holds it, and a second press cannot resend it.
        apiKey = ""
        busy = true
        message = ""
        defer { busy = false }
        do {
            switch try await client.setAIKey(submission) {
            case .applied:
                return await confirmGatewayReady()
            case let .pendingHuman(raised):
                // The server raised an approval for the person's own submission; they are the
                // one it would ask, so the same press answers it.
                return await approveAndConnect(raised)
            case .pending:
                message = Copy.waiting
                return false
            case let .refused(reason):
                message = BoltrigError.plainCopy(for: reason)
                return false
            }
        } catch {
            message = Self.describe(error)
            return false
        }
    }

    private func approveAndConnect(_ current: AIKeyProposal) async -> Bool {
        busy = true
        message = ""
        defer { busy = false }
        do {
            switch try await client.approveProposal(id: current.id) {
            case .applied:
                proposal = nil
                return await confirmGatewayReady()
            case let .pending(next), let .pendingHuman(next):
                // The decision genuinely sits with an administrator. Keep the request so the
                // next press re-checks it instead of submitting the key again.
                proposal = next
                message = Copy.waiting
                return false
            case let .refused(reason):
                // Any other state is dead; holding it would answer the same dead request on
                // every press, so it is dropped and the next press starts fresh.
                proposal = nil
                message = BoltrigError.plainCopy(for: reason)
                return false
            }
        } catch {
            proposal = nil
            message = Self.describe(error)
            return false
        }
    }

    private func activate(_ existing: AIKeyView) async -> Bool {
        busy = true
        message = ""
        defer { busy = false }
        do {
            switch try await client.activateAIKey(level: existing.level, scopeID: existing.scopeID, modality: existing.modality) {
            case .applied:
                return await confirmGatewayReady()
            case .pending, .pendingHuman:
                message = Copy.waiting
                return false
            case let .refused(reason):
                message = BoltrigError.plainCopy(for: reason)
                return false
            }
        } catch {
            message = Self.describe(error)
            return false
        }
    }

    /// A save that succeeded is not a provider that works. Read the keys back and say which
    /// of the two happened. Not knowing and knowing it is broken are different answers: an
    /// unreachable re-read lets the step pass, and only a server that positively says the
    /// provider did not answer holds it. The recovery needs the key typed again because the
    /// address is part of the sealed submission.
    private func confirmGatewayReady() async -> Bool {
        guard let refreshed = try? await client.aiKeys() else {
            message = Copy.savedUnconfirmed
            return true
        }
        readiness = refreshed
        if let key = refreshed.existingKey(userID: account.id, modality: modality), key.gatewayReady == false {
            message = Copy.savedNotAnswering
            return false
        }
        message = Copy.connected
        return true
    }

    static func describe(_ error: Error) -> String {
        if let error = error as? BoltrigError, let copy = error.errorDescription { return copy }
        return BoltrigError(kind: .unreachable, status: 0).errorDescription ?? ""
    }
}
