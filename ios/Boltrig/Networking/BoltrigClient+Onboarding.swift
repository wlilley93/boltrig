import Foundation

/// The routes first-run setup uses: the person's name, and the provider intake the web
/// app's onboarding drives. Every write here is the same call the browser makes.
extension BoltrigClient {
    /// Sets the name Boltrig greets the person by. The server collapses whitespace and
    /// refuses anything outside 1 to 80 ordinary characters with a reason the phone maps.
    func updateProfile(displayName: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["display_name": displayName])
        _ = try await perform(path: "/v1/me/profile", method: "PATCH", body: body)
    }

    /// Which providers are saved, whether each could be reached, and whether the person may
    /// add their own. Never returns a key.
    func aiKeys() async throws -> AIKeysReadiness {
        let (data, _) = try await perform(path: "/v1/ai-keys", method: "GET", body: nil)
        return try AIKeysReadiness.decode(data)
    }

    /// Saves a provider and its key once. 200 means applied; 202 means the server raised
    /// an approval, answered in the same press by `approveProposal`.
    func setAIKey(_ submission: AIKeySubmission) async throws -> AIKeyOutcome {
        let body = try JSONSerialization.data(withJSONObject: submission.wireForm)
        return try await aiKeyOutcome(path: "/v1/ai-keys", method: "PUT", body: body)
    }

    /// Answers the person's own pending approval and applies the key. 202 with `pending`
    /// means the decision belongs to an administrator.
    func approveProposal(id: String) async throws -> AIKeyOutcome {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        let body = try JSONSerialization.data(withJSONObject: [String: String]())
        return try await aiKeyOutcome(path: "/v1/ai-keys/proposals/\(encoded)/approve", method: "POST", body: body)
    }

    /// Binds a key that is already saved so the provider can be used. A saved key whose
    /// provider does not answer comes back as a refusal carrying the server's sentence.
    func activateAIKey(level: String, scopeID: String, modality: String) async throws -> AIKeyOutcome {
        let body = try JSONSerialization.data(withJSONObject: ["level": level, "scope_id": scopeID, "modality": modality])
        return try await aiKeyOutcome(path: "/v1/ai-keys/activate", method: "POST", body: body)
    }

    /// The three provider routes answer refusals with a sentence for the person reading
    /// it, on 4xx and on 503 alike. Those become `.refused`; anything without a sentence
    /// (no network, a dead token, a throttle, a bare 5xx) is still thrown.
    private func aiKeyOutcome(path: String, method: String, body: Data?) async throws -> AIKeyOutcome {
        do {
            let (data, _) = try await perform(path: path, method: method, body: body)
            return AIKeyOutcome.decode(data)
        } catch let error as BoltrigError {
            switch error.kind {
            case let .rejected(reason):
                return .refused(reason: reason)
            case let .server(_, reason?):
                return .refused(reason: reason)
            default:
                throw error
            }
        }
    }
}
