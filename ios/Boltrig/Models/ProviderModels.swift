import Foundation

/// Which kind of model a saved provider serves. The server keeps one key per modality.
enum AIModality: String, Equatable {
    case text
    case vision
}

/// One saved provider as the server lists it: what is bound, never the key itself.
struct AIKeyView: Equatable {
    let level: String
    let scopeID: String
    let provider: String
    let model: String
    let modality: String
    let baseURL: String?
    let hasKey: Bool
    /// Whether the server could reach the provider with this key when it was asked;
    /// nil when the server did not say (an older server, or the check was skipped).
    let gatewayReady: Bool?
    let updatedAt: String?

    init(level: String, scopeID: String, provider: String, model: String, modality: String = "text",
         baseURL: String? = nil, hasKey: Bool = true, gatewayReady: Bool? = nil, updatedAt: String? = nil) {
        self.level = level
        self.scopeID = scopeID
        self.provider = provider
        self.model = model
        self.modality = modality
        self.baseURL = baseURL
        self.hasKey = hasKey
        self.gatewayReady = gatewayReady
        self.updatedAt = updatedAt
    }

    /// The model as the person typed or chose it, without the provider prefix the server stores.
    var modelLabel: String {
        let prefix = provider + "/"
        return model.hasPrefix(prefix) ? String(model.dropFirst(prefix.count)) : model
    }

    static func decode(_ object: [String: Any]) -> AIKeyView? {
        guard let level = object["level"] as? String, let scopeID = object["scope_id"] as? String else { return nil }
        return AIKeyView(
            level: level,
            scopeID: scopeID,
            provider: object["provider"] as? String ?? "",
            model: object["model"] as? String ?? "",
            modality: (object["modality"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "text",
            baseURL: object["base_url"] as? String,
            hasKey: object["has_key"] as? Bool ?? false,
            gatewayReady: object["gateway_ready"] as? Bool,
            updatedAt: object["updated_at"] as? String
        )
    }
}

/// The answer to "which providers are saved, and may this person add their own?".
struct AIKeysReadiness: Equatable {
    let allowOwn: Bool
    let keys: [AIKeyView]

    /// The person's own key for one modality, if they have saved one.
    func existingKey(userID: String, modality: AIModality) -> AIKeyView? {
        keys.first { $0.level == "user" && $0.scopeID == userID && $0.modality == modality.rawValue }
    }

    static func decode(_ data: Data) throws -> AIKeysReadiness {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        let rows = root["ai_keys"] as? [[String: Any]] ?? []
        return AIKeysReadiness(allowOwn: Account.flag(root["allow_own_ai_keys"]), keys: rows.compactMap(AIKeyView.decode))
    }
}

/// A key submission the server has sealed but not yet applied, waiting on an approval.
struct AIKeyProposal: Equatable, Identifiable {
    let id: String
    let provider: String
    let model: String
    let modality: String
    let status: String

    static func decode(_ object: [String: Any]?) -> AIKeyProposal? {
        guard let object, let id = object["id"] as? String, !id.isEmpty else { return nil }
        return AIKeyProposal(
            id: id,
            provider: object["provider"] as? String ?? "",
            model: object["model"] as? String ?? "",
            modality: (object["modality"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "text",
            status: object["status"] as? String ?? ""
        )
    }
}

/// What the phone sends once to save a provider. The key travels in this value and nowhere else.
struct AIKeySubmission: Equatable {
    let level: String
    let provider: String
    let model: String
    let modality: AIModality
    let baseURL: String?
    let apiKey: String

    /// The field is always sent, empty for a self-hosted server that authenticates nothing,
    /// exactly as the web does.
    var wireForm: [String: Any] {
        var body: [String: Any] = [
            "level": level,
            "provider": provider,
            "model": model,
            "modality": modality.rawValue,
            "api_key": apiKey,
        ]
        if let baseURL, !baseURL.isEmpty { body["base_url"] = baseURL }
        return body
    }
}

/// What a save, an approval or an activation resolved to. Refusals the server explains are
/// outcomes here, not thrown errors, so the sentence reaches the screen unchanged.
enum AIKeyOutcome: Equatable {
    /// Saved and bound; the provider is ready to be checked.
    case applied
    /// The server raised an approval for this submission; the same press answers it.
    case pendingHuman(AIKeyProposal)
    /// The decision sits with an administrator; the proposal is kept for the next press.
    case pending(AIKeyProposal)
    /// Not saved; the reason is the server's own sentence, or empty when it gave none.
    case refused(reason: String)

    static func decode(_ data: Data) -> AIKeyOutcome {
        let object = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        let status = object["status"] as? String ?? ""
        let reason = object["reason"] as? String
        let proposal = AIKeyProposal.decode(object["proposal"] as? [String: Any])
        switch status {
        case "ok":
            return .applied
        case "pending_human":
            if let proposal { return .pendingHuman(proposal) }
            return .refused(reason: reason ?? "")
        case "pending":
            if let proposal { return .pending(proposal) }
            return .refused(reason: reason ?? "")
        default:
            return .refused(reason: reason ?? "")
        }
    }
}
