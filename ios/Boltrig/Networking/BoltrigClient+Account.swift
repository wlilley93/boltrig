import Foundation

extension BoltrigClient {
    // MARK: Approvals (read-only on the phone)

    /// The server refuses `PUT` on this route for the phone's key, so the phone only reads.
    func approvalPosture() async throws -> ApprovalPostureReading {
        let (data, _) = try await perform(path: "/v1/me/approval-posture", method: "GET", body: nil)
        return try ApprovalPostureReading.decode(data)
    }

    // MARK: Sessions and keys

    func sessions() async throws -> [UserSession] {
        let (data, _) = try await perform(path: "/v1/me/sessions", method: "GET", body: nil)
        return try UserSession.decodeList(data)
    }

    func revokeSession(id: String) async throws {
        _ = try await perform(path: "/v1/me/sessions/\(id)", method: "DELETE", body: nil)
    }

    func tokens() async throws -> [AccessTokenView] {
        let (data, _) = try await perform(path: "/v1/me/tokens", method: "GET", body: nil)
        return try AccessTokenView.decodeList(data)
    }

    /// Revoking the key this phone signs in with signs the phone out; `SessionStore.signOut` does that.
    func revokeToken(id: String) async throws {
        try await revokeAccessToken(id: id)
    }

    // MARK: Spending

    func budgets() async throws -> [BudgetView] {
        let (data, _) = try await perform(path: "/v1/budgets", method: "GET", body: nil)
        return try BudgetView.decodeList(data)
    }

    func cost() async throws -> CostSummary {
        let (data, _) = try await perform(path: "/v1/cost", method: "GET", body: nil)
        return try CostSummary.decode(data)
    }

    // MARK: Health

    /// `GET /readyz` answers 503 when something required is down, with the same report in
    /// the body, so a 503 is an answer here and not a failure.
    func readiness() async throws -> ReadinessReport {
        let request = try makeRequest(path: "/readyz", method: "GET", body: nil)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw BoltrigError(kind: .unreachable, status: 0)
        }
        guard let http = response as? HTTPURLResponse else {
            throw BoltrigError(kind: .invalidResponse, status: 0)
        }
        guard (200..<300).contains(http.statusCode) || http.statusCode == 503 else {
            throw Self.mapError(status: http.statusCode, data: data)
        }
        return try ReadinessReport.decode(data)
    }

    // MARK: Account deletion

    /// Not available yet: no server route exists. Kept behind
    /// `BoltrigEnvironment.accountDeletionAvailable` so nothing calls it until one does.
    func deleteAccount(password: String) async throws {
        guard BoltrigEnvironment.accountDeletionAvailable else {
            throw BoltrigError(kind: .rejected(reason: "deleting your account from the app is not available yet"), status: 0)
        }
        let body = try JSONSerialization.data(withJSONObject: ["password": password])
        _ = try await perform(path: "/v1/me", method: "DELETE", body: body)
    }
}
