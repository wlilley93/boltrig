import Foundation

#if DEBUG
/// A server that answers only what first-run setup asks, so the simulator can show every setup
/// step without an account: `-boltrigOnboarding`, optionally `-boltrigStep name|provider|vision|ready`.
/// Debug builds only; nothing here ships.
final class SetupPreviewProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    override func startLoading() {
        let path = request.url?.path ?? ""
        let method = request.httpMethod ?? "GET"
        let body: [String: Any]
        switch (method, path) {
        case ("GET", "/v1/ai-keys"):
            body = ["allow_own_ai_keys": true, "ai_keys": []]
        case ("GET", "/v1/me/settings"):
            body = SetupPreview.accountJSON
        case ("PUT", "/v1/ai-keys"), ("POST", "/v1/ai-keys/activate"), ("PATCH", "/v1/me/profile"),
             ("PUT", "/v1/me/settings"), ("POST", "/v1/familiar/emotion/adopted"):
            body = ["status": "ok"]
        default:
            body = ["status": "error", "reason": "not in the setup preview"]
        }
        let data = (try? JSONSerialization.data(withJSONObject: body)) ?? Data()
        let status = (body["status"] as? String) == "error" ? 404 : 200
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
}

enum SetupPreview {
    static let accountJSON: [String: Any] = [
        "profile": ["id": "preview", "email": "preview@example.com", "display_name": "", "role": "member",
                    "scope": "workspace", "status": "active", "source": "invite"],
        "active_workspace_id": "preview-workspace",
        "settings": [:],
        "setting_sources": [:],
    ]

    static func account() -> Account {
        Account(id: "preview", email: "preview@example.com", displayName: "", role: "member",
                activeWorkspaceID: "preview-workspace", onboardingComplete: false, characterID: nil)
    }

    static func client() -> BoltrigClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SetupPreviewProtocol.self]
        return BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("preview"),
                             session: URLSession(configuration: configuration))
    }

    /// The store for the preview, moved to the requested step with enough filled in to render it.
    @MainActor
    static func store(step: String?) -> OnboardingStore {
        let store = OnboardingStore(client: client(), account: account())
        switch step {
        case "provider": store.debugJump(to: .provider, name: "Alex")
        case "vision": store.debugJump(to: .vision, name: "Alex")
        case "ready": store.debugJump(to: .ready, name: "Alex")
        default: break
        }
        return store
    }
}
#endif
