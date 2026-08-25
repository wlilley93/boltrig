import Foundation

/// Answers URLSession requests from an in-memory table so the session and client can be
/// exercised without a server. Keyed by "METHOD /path".
final class StubURLProtocol: URLProtocol {
    struct Answer {
        var status: Int
        var body: Data
        var headers: [String: String] = ["Content-Type": "application/json"]
        var fail: Bool = false
    }

    nonisolated(unsafe) static var answers: [String: (URLRequest) -> Answer] = [:]
    nonisolated(unsafe) static var requests: [URLRequest] = []
    private static let lock = NSLock()

    static func reset() {
        lock.lock(); defer { lock.unlock() }
        answers = [:]
        requests = []
    }

    static func on(_ method: String, _ path: String, _ answer: @escaping (URLRequest) -> Answer) {
        lock.lock(); defer { lock.unlock() }
        answers["\(method) \(path)"] = answer
    }

    static func json(_ status: Int, _ object: Any) -> Answer {
        Answer(status: status, body: try! JSONSerialization.data(withJSONObject: object))
    }

    static func recorded(_ method: String, _ path: String) -> [URLRequest] {
        lock.lock(); defer { lock.unlock() }
        return requests.filter { $0.httpMethod == method && $0.url?.path == path }
    }

    static func body(of request: URLRequest) -> Data {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let size = 4096
        var buffer = [UInt8](repeating: 0, count: size)
        while stream.hasBytesAvailable {
            let read = stream.read(&buffer, maxLength: size)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let request = self.request
        let key = "\(request.httpMethod ?? "GET") \(request.url?.path ?? "")"
        Self.lock.lock()
        Self.requests.append(request)
        let handler = Self.answers[key]
        Self.lock.unlock()
        guard let handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let answer = handler(request)
        if answer.fail {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: answer.status, httpVersion: "HTTP/1.1", headerFields: answer.headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: answer.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

enum Fixtures {
    static let stubbedConfiguration: URLSessionConfiguration = {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        return config
    }()

    static func ok(csrf: String = "csrf-1") -> [String: Any] {
        ["status": "ok", "csrf_token": csrf, "user": ["id": "u1", "email": "ada@example.com", "role": "member"]]
    }

    static let settings: [String: Any] = [
        "profile": ["id": "u1", "email": "ada@example.com", "display_name": "Ada Lovelace", "role": "member",
                    "scope": "workspace", "status": "active", "source": "invite", "source_group": NSNull(), "last_seen_at": NSNull()],
        "active_workspace_id": "ws1",
        "settings": ["setup.onboarding_version": 1, "agent.character": "familiar", "theme": "dark"],
        "setting_sources": ["theme": "user_override"],
    ]

    /// An account whose companion was chosen on the web and is not Familiar. The id is a
    /// neutral placeholder: the phone never displays it and the bundle names no other companion.
    static var settingsOtherCharacter: [String: Any] {
        var copy = settings
        copy["settings"] = ["setup.onboarding_version": 1, "agent.character": "another-character"]
        return copy
    }

    static var settingsNoCharacter: [String: Any] {
        var copy = settings
        copy["settings"] = ["setup.onboarding_version": 1]
        return copy
    }

    /// The familiar-only adoption routes answer ok.
    static func stubAdoption() {
        StubURLProtocol.on("PUT", "/v1/me/settings") { _ in StubURLProtocol.json(200, ["status": "ok", "keys": ["agent.character"]]) }
        StubURLProtocol.on("POST", "/v1/familiar/emotion/adopted") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
    }

    static func stubHappyTokenPath() {
        StubURLProtocol.on("POST", "/v1/me/tokens") { _ in
            StubURLProtocol.json(200, ["status": "ok", "id": "tok1", "name": "iPhone", "secret": "boltrig_pat_secret"])
        }
        StubURLProtocol.on("POST", "/v1/auth/logout") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        StubURLProtocol.on("GET", "/v1/me/settings") { _ in StubURLProtocol.json(200, settings) }
    }
}
