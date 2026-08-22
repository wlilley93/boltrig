import XCTest
@testable import Boltrig

/// Shared fixtures for the first-run setup tests. Everything here is nonisolated so the stub
/// handlers, which run on the loader's thread, can use it too.
enum OnboardingFixtures {
    static func client() -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_x"),
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    static func account(role: String = "member", name: String = "Ada Lovelace", onboarded: Bool = false) -> Account {
        Account(id: "u1", email: "ada@example.com", displayName: name, role: role, activeWorkspaceID: "ws1",
                onboardingComplete: onboarded, characterID: nil)
    }

    /// A handful of providers that exercise every rule without decoding the 400 KB file.
    static let smallCatalogue: ProviderCatalogue = {
        let json: [String: Any] = [
            "source": "test", "revision": "test-rev", "license": "MIT",
            "providers": [
                ["id": "openai", "name": "OpenAI", "models": [["id": "gpt-4.1", "name": "GPT-4.1", "vision": true], ["id": "o3-mini"]]],
                ["id": "deepseek", "name": "DeepSeek", "api": "https://api.deepseek.com", "models": [["id": "deepseek-chat"]]],
                ["id": "togetherai", "name": "Together", "models": [["id": "llama-3"]]],
                ["id": "ollama-cloud", "name": "Ollama Cloud", "api": "https://ollama.com/v1", "models": [["id": "gpt-oss:20b"]]],
                ["id": "custom", "name": "Custom / self-hosted", "models": []],
            ],
        ]
        return try! ProviderCatalogue.decode(try! JSONSerialization.data(withJSONObject: json))
    }()

    static func keyRow(gatewayReady: Bool?, modality: String = "text", provider: String = "openai",
                       model: String = "openai/gpt-4.1") -> [String: Any] {
        var row: [String: Any] = ["level": "user", "scope_id": "u1", "provider": provider, "model": model, "modality": modality,
                                  "base_url": NSNull(), "has_key": true, "updated_at": "2026-08-22T07:00:00+00:00"]
        if let gatewayReady { row["gateway_ready"] = gatewayReady }
        return row
    }

    static let proposal: [String: Any] = [
        "id": "akp_1", "level": "user", "scope_id": "u1", "provider": "openai", "model": "openai/gpt-4.1", "modality": "text",
        "base_url": NSNull(), "status": "pending", "created_at": "2026-08-22T07:00:00+00:00", "expires_at": "2026-08-22T08:00:00+00:00",
    ]

    static func stubKeys(allowOwn: Bool = true, keys: [[String: Any]] = []) {
        StubURLProtocol.on("GET", "/v1/ai-keys") { _ in StubURLProtocol.json(200, ["allow_own_ai_keys": allowOwn, "ai_keys": keys]) }
    }

    /// The three writes finishing makes, all answering ok.
    static func stubFinish() {
        StubURLProtocol.on("PATCH", "/v1/me/profile") { _ in StubURLProtocol.json(200, ["status": "ok", "profile": ["id": "u1"]]) }
        StubURLProtocol.on("PUT", "/v1/me/settings") { _ in
            StubURLProtocol.json(200, ["status": "ok", "keys": ["agent.character", "setup.onboarding_version"]])
        }
        StubURLProtocol.on("POST", "/v1/familiar/emotion/adopted") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
    }

    static func sentJSON(_ request: URLRequest) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.body(of: request)) as? [String: Any])
    }
}

/// A value written from a stub handler's thread and read back on the test's.
final class CapturedValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Value?

    var value: Value? {
        get { lock.lock(); defer { lock.unlock() }; return stored }
        set { lock.lock(); defer { lock.unlock() }; stored = newValue }
    }
}

final class CallCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    /// Increments and returns the new count.
    func next() -> Int {
        lock.lock(); defer { lock.unlock() }
        count += 1
        return count
    }
}
