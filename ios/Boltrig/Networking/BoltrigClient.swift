import Foundation

/// What the client sends to prove who it is.
enum Authorization: Equatable {
    /// Nothing yet: sign-in and the public recovery routes.
    case none
    /// A cookie session held by this client's URLSession, plus the value every write must echo.
    case session(csrfToken: String)
    /// A personal access token minted for this phone. No cookies, no extra headers.
    case accessToken(String)
}

/// The HTTP surface the phone uses. One instance, one authorization, one URLSession.
struct BoltrigClient {
    let baseURL: URL
    let authorization: Authorization
    let session: URLSession

    static let csrfHeader = "x-boltrig-csrf"
    private static let mutatingMethods: Set<String> = ["POST", "PUT", "PATCH", "DELETE"]

    init(baseURL: URL, authorization: Authorization, session: URLSession) {
        self.baseURL = baseURL
        self.authorization = authorization
        self.session = session
    }

    // MARK: Sign-in and account security

    func login(email: String, password: String) async throws -> SignInOutcome {
        let body = try JSONSerialization.data(withJSONObject: ["email": email, "password": password])
        let (data, _) = try await perform(path: "/v1/auth/login", method: "POST", body: body)
        return try Self.decodeSignIn(data)
    }

    func completeTwoFactor(challengeToken: String, code: String) async throws -> SignInOutcome {
        let body = try JSONSerialization.data(withJSONObject: ["challenge_token": challengeToken, "code": code])
        let (data, _) = try await perform(path: "/v1/auth/2fa/challenge", method: "POST", body: body)
        return try Self.decodeSignIn(data)
    }

    func changePassword(current: String, new: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["current_password": current, "new_password": new])
        _ = try await perform(path: "/v1/auth/change-password", method: "POST", body: body)
    }

    func beginTwoFactorEnrolment() async throws -> TwoFactorEnrolment {
        let (data, _) = try await perform(path: "/v1/auth/2fa/enroll", method: "POST", body: nil)
        return try decode(TwoFactorEnrolment.self, from: data)
    }

    /// Returns how many recovery codes remain unused.
    func verifyTwoFactorEnrolment(code: String) async throws -> Int {
        let body = try JSONSerialization.data(withJSONObject: ["code": code])
        let (data, _) = try await perform(path: "/v1/auth/2fa/verify-enroll", method: "POST", body: body)
        let object = try jsonObject(from: data)
        return object["recovery_codes_remaining"] as? Int ?? 0
    }

    func requestPasswordReset(email: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["email": email])
        _ = try await perform(path: "/v1/auth/password-reset/request", method: "POST", body: body)
    }

    func logout() async throws {
        _ = try await perform(path: "/v1/auth/logout", method: "POST", body: nil)
    }

    func mintAccessToken(name: String, ttlDays: Int) async throws -> MintedAccessToken {
        let body = try JSONSerialization.data(withJSONObject: ["name": name, "ttl_days": ttlDays])
        let (data, _) = try await perform(path: "/v1/me/tokens", method: "POST", body: body)
        let object = try jsonObject(from: data)
        guard let id = object["id"] as? String, let secret = object["secret"] as? String, !secret.isEmpty else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        return MintedAccessToken(id: id, secret: secret)
    }

    func revokeAccessToken(id: String) async throws {
        _ = try await perform(path: "/v1/me/tokens/\(id)", method: "DELETE", body: nil)
    }

    func account() async throws -> Account {
        let (data, _) = try await perform(path: "/v1/me/settings", method: "GET", body: nil)
        return try Account.decode(data)
    }

    /// Writes user settings by key. The server refuses the approval posture and sensing keys
    /// here; those have their own routes.
    func putSettings(_ values: [String: Any]) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["settings": values])
        _ = try await perform(path: "/v1/me/settings", method: "PUT", body: body)
    }

    /// Tells the companion's inner life that it has been chosen; purely cosmetic on the server.
    func announceAdopted(character: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["character": character])
        _ = try await perform(path: "/v1/familiar/emotion/adopted", method: "POST", body: body)
    }

    // MARK: Work

    func conversations() async throws -> [ConversationSummary] {
        struct Envelope: Decodable { let conversations: [ConversationSummary] }
        let (data, _) = try await perform(path: "/v1/conversations", method: "GET", body: nil)
        return try decode(Envelope.self, from: data).conversations
    }

    func approvals() async throws -> [ApprovalRequest] {
        struct Envelope: Decodable { let requests: [ApprovalRequest] }
        let (data, _) = try await perform(path: "/v1/hitl", method: "GET", body: nil)
        return try decode(Envelope.self, from: data).requests
    }

    func respond(to approvalID: String, decision: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["decision": decision, "notes": ""])
        _ = try await perform(path: "/v1/hitl/\(approvalID)/respond", method: "POST", body: body)
    }

    func cancelRun(id: String) async throws {
        _ = try await perform(path: "/v1/runs/\(id)/cancel", method: "POST", body: nil)
    }

    /// Sends one message and streams the turn back. A 202 yields a single `.queued` event.
    func streamChat(message: String, conversationID: String?, idempotencyKey: String) -> AsyncThrowingStream<ChatEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var payload: [String: Any] = [
                        "message": message,
                        "origin": "ios",
                        "idempotency_key": idempotencyKey,
                        "attachments": [],
                    ]
                    if let conversationID { payload["conversation_id"] = conversationID }
                    let body = try JSONSerialization.data(withJSONObject: payload)
                    var request = try makeRequest(path: "/v1/chat", method: "POST", body: body, accept: "text/event-stream")
                    request.timeoutInterval = 600
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse else {
                        throw BoltrigError(kind: .invalidResponse, status: 0)
                    }
                    if http.statusCode == 202 {
                        var collected = Data()
                        for try await byte in bytes { collected.append(byte) }
                        let object = (try? JSONSerialization.jsonObject(with: collected) as? [String: Any]) ?? [:]
                        continuation.yield(.queued(conversationID: object["conversation_id"] as? String))
                        continuation.finish()
                        return
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        var collected = Data()
                        for try await byte in bytes { collected.append(byte) }
                        throw Self.mapError(status: http.statusCode, data: collected)
                    }
                    // Split lines by hand: the frame boundary is a blank line, and
                    // AsyncBytes.lines does not deliver empty lines.
                    var parser = SSEFrameParser()
                    var lineBuffer = Data()
                    for try await byte in bytes {
                        try Task.checkCancellation()
                        if byte == UInt8(ascii: "\n") {
                            if lineBuffer.last == UInt8(ascii: "\r") { lineBuffer.removeLast() }
                            let line = String(decoding: lineBuffer, as: UTF8.self)
                            lineBuffer.removeAll(keepingCapacity: true)
                            if let frame = parser.consume(line: line) {
                                continuation.yield(ChatEvent.from(json: frame))
                            }
                        } else {
                            lineBuffer.append(byte)
                        }
                    }
                    if !lineBuffer.isEmpty {
                        if lineBuffer.last == UInt8(ascii: "\r") { lineBuffer.removeLast() }
                        if let frame = parser.consume(line: String(decoding: lineBuffer, as: UTF8.self)) {
                            continuation.yield(ChatEvent.from(json: frame))
                        }
                    }
                    if let frame = parser.flush() {
                        continuation.yield(ChatEvent.from(json: frame))
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch let error as BoltrigError {
                    continuation.finish(throwing: error)
                } catch {
                    continuation.finish(throwing: BoltrigError(kind: .unreachable, status: 0))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: Plumbing

    func makeRequest(path: String, method: String, body: Data?, accept: String = "application/json") throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
            throw BoltrigError(kind: .invalidResponse, status: 0)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = 30
        request.setValue(accept, forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        switch authorization {
        case .none:
            break
        case let .session(csrfToken):
            if Self.mutatingMethods.contains(method) {
                request.setValue(csrfToken, forHTTPHeaderField: Self.csrfHeader)
            }
        case let .accessToken(token):
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    func perform(path: String, method: String, body: Data?) async throws -> (Data, HTTPURLResponse) {
        let request = try makeRequest(path: path, method: method, body: body)
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
        guard (200..<300).contains(http.statusCode) else {
            throw Self.mapError(status: http.statusCode, data: data)
        }
        return (data, http)
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
    }

    private func jsonObject(from data: Data) throws -> [String: Any] {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        return object
    }

    static func decodeSignIn(_ data: Data) throws -> SignInOutcome {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let status = object["status"] as? String else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        if status == "2fa_required" {
            guard let token = object["challenge_token"] as? String, !token.isEmpty else {
                throw BoltrigError(kind: .invalidResponse, status: 200)
            }
            return .twoFactorRequired(challengeToken: token)
        }
        guard let csrf = object["csrf_token"] as? String,
              let userObject = object["user"] as? [String: Any],
              let id = userObject["id"] as? String,
              let email = userObject["email"] as? String else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        let user = SignedInUser(id: id, email: email, role: userObject["role"] as? String ?? "")
        switch status {
        case "ok":
            return .signedIn(csrfToken: csrf, user: user)
        case "password_change_required":
            return .passwordChangeRequired(csrfToken: csrf, user: user)
        case "2fa_enrollment_required":
            return .twoFactorEnrolmentRequired(csrfToken: csrf, user: user)
        default:
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
    }

    /// Reduces a non-2xx answer to a `BoltrigError`. The server uses two envelopes,
    /// `{"status":"error","reason":…}` and `{"detail":…}`; both are read.
    static func mapError(status: Int, data: Data) -> BoltrigError {
        let reason = reason(in: data)
        switch status {
        case 401:
            // The sign-in routes answer 401 with a reason the person can act on ("invalid email
            // or password", "invalid or expired code"). A missing session or a dead token is the
            // only 401 that means "go and sign in".
            if let reason, !sessionReasons.contains(reason) {
                return BoltrigError(kind: .rejected(reason: reason), status: status)
            }
            return BoltrigError(kind: .unauthenticated, status: status)
        case 403:
            if reason == "password_change_required" {
                return BoltrigError(kind: .passwordChangeRequired, status: status)
            }
            if reason == "two_factor_enrollment_required" {
                return BoltrigError(kind: .twoFactorEnrolmentRequired, status: status)
            }
            return BoltrigError(kind: .forbidden, status: status)
        case 429:
            return BoltrigError(kind: .throttled, status: status)
        case 400..<500:
            return BoltrigError(kind: .rejected(reason: reason ?? ""), status: status)
        default:
            return BoltrigError(kind: .server(status: status), status: status)
        }
    }

    /// 401 reasons that mean the credential itself is gone, as opposed to a wrong answer.
    static let sessionReasons: Set<String> = [
        "no session", "session expired", "invalid or expired access token", "not authenticated", "unauthorized",
    ]

    static func reason(in data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let reason = object["reason"] as? String { return reason }
        if let detail = object["detail"] as? String { return detail }
        if let error = object["error"] as? String { return error }
        return nil
    }
}
