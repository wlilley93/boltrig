import XCTest
@testable import Boltrig

@MainActor
final class SessionStoreTests: XCTestCase {
    private var vault: InMemorySessionVault!
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
        vault = InMemorySessionVault()
        defaults = UserDefaults(suiteName: "SessionStoreTests-\(UUID().uuidString)")
    }

    private func makeStore() -> SessionStore {
        SessionStore(vault: vault, configuration: Fixtures.stubbedConfiguration, defaults: defaults)
    }

    func testSignInMintsAPhoneTokenAndLoadsTheAccount() async throws {
        StubURLProtocol.on("POST", "/v1/auth/login") { _ in StubURLProtocol.json(200, Fixtures.ok()) }
        Fixtures.stubHappyTokenPath()
        let store = makeStore()

        await store.signIn(email: "ada@example.com", password: "correct horse battery")

        guard case let .signedIn(account) = store.state else {
            return XCTFail("expected signedIn, got \(store.state), error \(store.errorMessage ?? "nil")")
        }
        XCTAssertEqual(account.displayName, "Ada Lovelace")
        XCTAssertEqual(account.companionName, "Ultron")
        XCTAssertTrue(account.onboardingComplete)
        XCTAssertEqual(vault.stored?.secret, "boltrig_pat_secret")
        XCTAssertEqual(vault.stored?.tokenID, "tok1")

        let mint = try XCTUnwrap(StubURLProtocol.recorded("POST", "/v1/me/tokens").first)
        XCTAssertEqual(mint.value(forHTTPHeaderField: BoltrigClient.csrfHeader), "csrf-1")
        XCTAssertNil(mint.value(forHTTPHeaderField: "Authorization"))
        let mintBody = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.body(of: mint)) as? [String: Any])
        XCTAssertEqual(mintBody["ttl_days"] as? Int, BoltrigEnvironment.accessTokenLifetimeDays)

        let me = try XCTUnwrap(StubURLProtocol.recorded("GET", "/v1/me/settings").first)
        XCTAssertEqual(me.value(forHTTPHeaderField: "Authorization"), "Bearer boltrig_pat_secret")
        XCTAssertNil(me.value(forHTTPHeaderField: BoltrigClient.csrfHeader))
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/auth/logout").count, 1, "the cookie session is closed once the token exists")
    }

    func testWrongPasswordStaysSignedOutWithPlainCopy() async {
        StubURLProtocol.on("POST", "/v1/auth/login") { _ in
            StubURLProtocol.json(401, ["status": "error", "reason": "invalid email or password"])
        }
        let store = makeStore()
        await store.signIn(email: "ada@example.com", password: "nope")
        XCTAssertEqual(store.state, .signedOut)
        XCTAssertEqual(store.errorMessage, "That email and password did not match.")
        XCTAssertNil(vault.stored)
    }

    func testTwoFactorRequiredAsksForTheCodeThenSignsIn() async {
        StubURLProtocol.on("POST", "/v1/auth/login") { _ in
            StubURLProtocol.json(200, ["status": "2fa_required", "challenge_token": "ch1"])
        }
        StubURLProtocol.on("POST", "/v1/auth/2fa/challenge") { request in
            let body = (try? JSONSerialization.jsonObject(with: StubURLProtocol.body(of: request)) as? [String: Any]) ?? [:]
            guard body["challenge_token"] as? String == "ch1", body["code"] as? String == "123456" else {
                return StubURLProtocol.json(401, ["status": "error", "reason": "invalid or expired code"])
            }
            return StubURLProtocol.json(200, Fixtures.ok(csrf: "csrf-2"))
        }
        Fixtures.stubHappyTokenPath()
        let store = makeStore()

        await store.signIn(email: "ada@example.com", password: "pw")
        XCTAssertEqual(store.state, .twoFactor(challengeToken: "ch1"))
        XCTAssertNil(vault.stored, "no session exists until the code is accepted")

        await store.submitTwoFactorCode("000000")
        XCTAssertEqual(store.state, .twoFactor(challengeToken: "ch1"))
        XCTAssertEqual(store.errorMessage, BoltrigError.plainCopy(for: "invalid or expired code"))

        await store.submitTwoFactorCode("123456")
        guard case .signedIn = store.state else { return XCTFail("expected signedIn, got \(store.state)") }
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/me/tokens").first?.value(forHTTPHeaderField: BoltrigClient.csrfHeader), "csrf-2")
    }

    func testForcedPasswordChangeIsCompletedBeforeTheTokenIsMinted() async {
        StubURLProtocol.on("POST", "/v1/auth/login") { _ in
            var outcome = Fixtures.ok()
            outcome["status"] = "password_change_required"
            return StubURLProtocol.json(200, outcome)
        }
        StubURLProtocol.on("POST", "/v1/auth/change-password") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        Fixtures.stubHappyTokenPath()
        let store = makeStore()

        await store.signIn(email: "ada@example.com", password: "old password 12")
        XCTAssertEqual(store.state, .passwordChange(csrfToken: "csrf-1"))

        await store.changePassword(current: "old password 12", new: "short", confirmation: "short")
        XCTAssertEqual(store.state, .passwordChange(csrfToken: "csrf-1"))
        XCTAssertNotNil(store.errorMessage)
        XCTAssertTrue(StubURLProtocol.recorded("POST", "/v1/auth/change-password").isEmpty, "a too-short password never leaves the phone")

        await store.changePassword(current: "old password 12", new: "a much longer password", confirmation: "a much longer password")
        guard case .signedIn = store.state else { return XCTFail("expected signedIn, got \(store.state)") }
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/auth/change-password").first?.value(forHTTPHeaderField: BoltrigClient.csrfHeader), "csrf-1")
    }

    func testRestoreWithARevokedTokenSignsOut() async {
        vault.stored = StoredSession(instanceURL: BoltrigEnvironment.hostedInstanceURL, tokenID: "tok1", secret: "boltrig_pat_old", createdAt: Date())
        StubURLProtocol.on("GET", "/v1/me/settings") { _ in
            StubURLProtocol.json(401, ["detail": "invalid or expired access token"])
        }
        let store = makeStore()
        await store.restore()
        XCTAssertEqual(store.state, .signedOut)
        XCTAssertNil(vault.stored)
    }

    func testRestoreWhileOfflineKeepsTheToken() async {
        vault.stored = StoredSession(instanceURL: BoltrigEnvironment.hostedInstanceURL, tokenID: "tok1", secret: "boltrig_pat_old", createdAt: Date())
        StubURLProtocol.on("GET", "/v1/me/settings") { _ in
            StubURLProtocol.Answer(status: 0, body: Data(), fail: true)
        }
        let store = makeStore()
        await store.restore()
        XCTAssertEqual(store.state, .unreachable)
        XCTAssertEqual(vault.stored?.secret, "boltrig_pat_old")
    }

    func testRestoreForAnotherInstanceDiscardsTheToken() async {
        vault.stored = StoredSession(instanceURL: URL(string: "https://other.example.com")!, tokenID: "tok1", secret: "s", createdAt: Date())
        let store = makeStore()
        await store.restore()
        XCTAssertEqual(store.state, .signedOut)
        XCTAssertNil(vault.stored)
        XCTAssertTrue(StubURLProtocol.requests.isEmpty, "a token for another instance is never sent anywhere")
    }

    func testSignOutRevokesThePhoneToken() async {
        StubURLProtocol.on("POST", "/v1/auth/login") { _ in StubURLProtocol.json(200, Fixtures.ok()) }
        Fixtures.stubHappyTokenPath()
        StubURLProtocol.on("DELETE", "/v1/me/tokens/tok1") { _ in StubURLProtocol.json(200, ["status": "ok", "id": "tok1"]) }
        let store = makeStore()
        await store.signIn(email: "ada@example.com", password: "pw")
        guard case .signedIn = store.state else { return XCTFail("precondition") }

        await store.signOut()
        XCTAssertEqual(store.state, .signedOut)
        XCTAssertNil(vault.stored)
        let revoke = StubURLProtocol.recorded("DELETE", "/v1/me/tokens/tok1")
        XCTAssertEqual(revoke.count, 1)
        XCTAssertEqual(revoke.first?.value(forHTTPHeaderField: "Authorization"), "Bearer boltrig_pat_secret")
    }

    func testChangingInstancePersistsAndSignsOut() async {
        let store = makeStore()
        XCTAssertEqual(store.instanceURL, BoltrigEnvironment.hostedInstanceURL)
        await store.useInstance(URL(string: "https://boltrig.example.org")!)
        XCTAssertEqual(store.instanceURL.absoluteString, "https://boltrig.example.org")
        XCTAssertEqual(InstanceAddress.load(defaults: defaults).absoluteString, "https://boltrig.example.org")
        XCTAssertEqual(store.state, .signedOut)
    }
}
