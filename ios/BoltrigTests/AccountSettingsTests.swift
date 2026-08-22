import XCTest
@testable import Boltrig

@MainActor
final class AccountSettingsTests: XCTestCase {
    private var vault: InMemorySessionVault!
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
        vault = InMemorySessionVault(stored: StoredSession(instanceURL: BoltrigEnvironment.hostedInstanceURL, tokenID: "tok-phone",
                                                           secret: "boltrig_pat_phone", createdAt: Date()))
        defaults = UserDefaults(suiteName: "AccountSettingsTests-\(UUID().uuidString)")
    }

    private func client() -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_phone"),
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    private func session() -> SessionStore {
        SessionStore(vault: vault, configuration: Fixtures.stubbedConfiguration, defaults: defaults)
    }

    private func store(session: SessionStore? = nil, account: Account = Account.preview) -> AccountSettingsStore {
        AccountSettingsStore(client: client(), account: account, session: session)
    }

    private func body(_ request: URLRequest) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.body(of: request)) as? [String: Any])
    }

    // MARK: Look and voice

    func testAppearanceWritesAllFiveKeysInOnePut() async throws {
        StubURLProtocol.on("PUT", "/v1/me/settings") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        let settings = store()
        var next = settings.appearance
        next.theme = .light
        next.density = .compact
        next.fontScale = "1.25"
        next.reducedMotion = true
        await settings.saveAppearance(next)

        XCTAssertEqual(settings.appearance, next)
        XCTAssertNil(settings.notice)
        let puts = StubURLProtocol.recorded("PUT", "/v1/me/settings")
        XCTAssertEqual(puts.count, 1, "the five keys travel together")
        let written = try XCTUnwrap(try body(puts[0])["settings"] as? [String: Any])
        XCTAssertEqual(written.count, 5)
        XCTAssertEqual(written["theme"] as? String, "light")
        XCTAssertEqual(written["density"] as? String, "compact")
        XCTAssertEqual(written["font_scale"] as? String, "1.25")
        XCTAssertEqual(written["a11y.reduced_motion"] as? Bool, true)
        XCTAssertEqual(written["a11y.high_contrast"] as? Bool, false)
    }

    func testAppearanceRollsBackWhenTheWriteFails() async {
        StubURLProtocol.on("PUT", "/v1/me/settings") { _ in StubURLProtocol.json(500, ["status": "error"]) }
        let settings = store()
        let before = settings.appearance
        var next = before
        next.theme = .light
        await settings.saveAppearance(next)

        XCTAssertEqual(settings.appearance, before)
        XCTAssertEqual(settings.notice, "Your appearance could not be saved.")
    }

    func testReadRepliesToggleWritesTheKey() async throws {
        StubURLProtocol.on("PUT", "/v1/me/settings") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        let settings = store()
        var told: Bool?
        settings.onReadRepliesChanged = { told = $0 }
        XCTAssertFalse(settings.readReplies)
        await settings.setReadReplies(true)

        XCTAssertTrue(settings.readReplies)
        XCTAssertEqual(told, true, "the speaker is told once the write succeeds")
        let put = try XCTUnwrap(StubURLProtocol.recorded("PUT", "/v1/me/settings").first)
        let written = try XCTUnwrap(try body(put)["settings"] as? [String: Any])
        XCTAssertEqual(written.count, 1)
        XCTAssertEqual(written["voice.read_replies"] as? Bool, true)
    }

    // MARK: Approvals

    func testReadRepliesRollsBackAndTellsNobodyWhenTheWriteFails() async {
        StubURLProtocol.on("PUT", "/v1/me/settings") { _ in StubURLProtocol.json(500, ["status": "error"]) }
        let settings = store()
        var told: Bool?
        settings.onReadRepliesChanged = { told = $0 }
        await settings.setReadReplies(true)

        XCTAssertFalse(settings.readReplies)
        XCTAssertNil(told)
        XCTAssertEqual(settings.notice, "Read out replies could not be changed.")
    }

    func testPostureIsReadAndNeverWritten() async {
        StubURLProtocol.on("GET", "/v1/me/approval-posture") { _ in
            StubURLProtocol.json(200, ["posture": "risk_based", "source": "user_override", "enforcement": ["applies_to": "delegated_agent_adapter_calls"]])
        }
        let settings = store()
        await settings.loadPosture()

        XCTAssertEqual(settings.posture?.posture, .riskBased)
        XCTAssertEqual(settings.posture?.posture.title, "Approve for me")
        XCTAssertEqual(StubURLProtocol.recorded("GET", "/v1/me/approval-posture").count, 1)
        XCTAssertTrue(StubURLProtocol.requests.filter { $0.httpMethod == "PUT" }.isEmpty, "the phone never writes the posture")
    }

    // MARK: Archived chats

    func testArchivedIsTheClosedConversationsAndRestoreBringsOneBack() async {
        StubURLProtocol.on("GET", "/v1/conversations") { _ in
            StubURLProtocol.json(200, ["conversations": [
                ["id": "c1", "title": "Open chat", "status": "Complete", "updated_at": "2026-08-20T10:00:00Z", "working": false],
                ["id": "c2", "title": "Old chat", "status": "closed", "updated_at": "2026-08-01T10:00:00Z", "working": false],
                ["id": "c3", "title": "Newer old chat", "status": "Closed", "updated_at": "2026-08-10T10:00:00Z", "working": false],
            ]])
        }
        StubURLProtocol.on("POST", "/v1/me/conversations/c3/restore") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        let settings = store()
        await settings.loadArchived()
        XCTAssertEqual(settings.archived.map(\.id), ["c3", "c2"], "closed only, newest activity first")

        let restored = await settings.restore(id: "c3")
        XCTAssertTrue(restored)
        XCTAssertEqual(settings.archived.map(\.id), ["c2"])
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/me/conversations/c3/restore").count, 1)
    }

    func testArchiveSoftClosesAChat() async {
        StubURLProtocol.on("DELETE", "/v1/me/conversations/c1") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        let settings = store()
        let archived = await settings.archive(id: "c1")
        XCTAssertTrue(archived)
        XCTAssertEqual(StubURLProtocol.recorded("DELETE", "/v1/me/conversations/c1").count, 1)
    }

    // MARK: Sessions and keys

    func testSessionsListAndRevoke() async {
        StubURLProtocol.on("GET", "/v1/me/sessions") { _ in
            StubURLProtocol.json(200, ["sessions": [
                ["id": "s1", "client": "web", "revoked": false, "created_at": "2026-08-20T10:00:00Z", "last_seen_at": "2026-08-21T10:00:00Z"],
                ["id": "s2", "client": NSNull(), "revoked": false, "created_at": NSNull(), "last_seen_at": NSNull()],
                ["id": "s3", "client": "desktop", "revoked": true, "created_at": "2026-08-01T10:00:00Z", "last_seen_at": NSNull()],
            ]])
        }
        StubURLProtocol.on("DELETE", "/v1/me/sessions/s1") { _ in StubURLProtocol.json(200, ["status": "ok", "id": "s1"]) }
        let settings = store()
        await settings.loadSessions()
        XCTAssertEqual(settings.sessions.map(\.id), ["s1", "s2"], "revoked sessions are not shown")
        XCTAssertEqual(settings.sessions[1].clientLabel, "Unknown client")
        XCTAssertEqual(settings.sessions[1].lastSeenLabel, "Not seen yet")

        let revoked = await settings.revokeSession(id: "s1")
        XCTAssertTrue(revoked)
        XCTAssertEqual(settings.sessions.map(\.id), ["s2"])
        XCTAssertEqual(StubURLProtocol.recorded("DELETE", "/v1/me/sessions/s1").count, 1)
    }

    func testTokensMarkThisPhoneAndRevokingItSignsOut() async {
        StubURLProtocol.on("GET", "/v1/me/tokens") { _ in
            StubURLProtocol.json(200, ["tokens": [
                ["id": "tok-phone", "name": "iPhone app, signed in 2026-08-22", "scope": ["*"], "created_at": "2026-08-22T08:00:00Z",
                 "last_used_at": NSNull(), "expires_at": "2026-11-20T08:00:00Z", "revoked": false],
                ["id": "tok-cli", "name": "Laptop", "scope": ["read"], "created_at": "2026-07-01T08:00:00Z",
                 "last_used_at": "2026-08-01T08:00:00Z", "expires_at": NSNull(), "revoked": false],
                ["id": "tok-old", "name": "Old", "scope": [], "created_at": NSNull(), "last_used_at": NSNull(), "expires_at": NSNull(), "revoked": true],
            ]])
        }
        StubURLProtocol.on("DELETE", "/v1/me/tokens/tok-cli") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        StubURLProtocol.on("DELETE", "/v1/me/tokens/tok-phone") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        let session = session()
        XCTAssertEqual(session.phoneTokenID, "tok-phone")
        let settings = store(session: session)
        await settings.loadTokens()

        XCTAssertEqual(settings.tokens.map(\.id), ["tok-phone", "tok-cli"], "revoked keys are not shown")
        XCTAssertTrue(settings.tokens[0].isThisPhone)
        XCTAssertFalse(settings.tokens[1].isThisPhone)
        XCTAssertEqual(settings.tokens[1].expiryLabel(), "Does not expire")
        XCTAssertEqual(settings.tokens[0].expiryLabel(now: LinkedDevice.date("2026-11-18T08:00:00Z")!), "Expires in 2 days")

        _ = await settings.revokeToken(id: "tok-cli")
        XCTAssertEqual(settings.tokens.map(\.id), ["tok-phone"])
        XCTAssertEqual(StubURLProtocol.recorded("DELETE", "/v1/me/tokens/tok-cli").count, 1)

        _ = await settings.revokeToken(id: "tok-phone")
        XCTAssertEqual(session.state, .signedOut, "revoking this phone's own key signs the phone out")
        XCTAssertNil(vault.stored)
        XCTAssertEqual(StubURLProtocol.recorded("DELETE", "/v1/me/tokens/tok-phone").count, 1)
    }

    // MARK: Spending and health

    func testSpendingDecodesBudgetsAndCost() async {
        StubURLProtocol.on("GET", "/v1/budgets") { _ in
            StubURLProtocol.json(200, ["budgets": [
                ["id": "b1", "scope_type": "tenant", "window": "monthly", "hard_stop": true, "token_limit": NSNull(),
                 "spent_tokens": 0, "cost_limit_micros": 40_000_000, "spent_micros": 12_400_000, "usage_state": "ok",
                 "window_key": "2026-08", "window_started_at": NSNull(), "window_ends_at": "2026-09-01T00:00:00Z"],
                ["id": "b2", "scope_type": "department", "window": "daily", "hard_stop": false, "token_limit": 250_000,
                 "spent_tokens": 1200, "cost_limit_micros": NSNull(), "spent_micros": 0, "usage_state": "ok",
                 "window_key": "2026-08-22", "window_started_at": NSNull(), "window_ends_at": NSNull()],
            ], "scope": "all"])
        }
        StubURLProtocol.on("GET", "/v1/cost") { _ in
            StubURLProtocol.json(200, ["total_cost_micros": 12_400_000, "by_actor": ["u1": 12_400_000], "scope": "all"])
        }
        let settings = store()
        await settings.loadSpending()

        XCTAssertEqual(settings.cost?.totalLabel, "$12.40")
        XCTAssertEqual(settings.budgets.count, 2)
        XCTAssertEqual(settings.budgets[0].title, "This month")
        XCTAssertEqual(settings.budgets[0].spentLabel, "$12.40 of $40.00")
        XCTAssertEqual(settings.budgets[0].note, "Work stops when this ceiling is reached.")
        XCTAssertEqual(settings.budgets[1].title, "Today, department")
        XCTAssertEqual(settings.budgets[1].spentLabel, "1,200 of 250,000")
        XCTAssertEqual(settings.budgets[1].note, "This ceiling counts usage, not money.")
    }

    func testReadinessTolerates503AndMapsPlainLabels() async {
        StubURLProtocol.on("GET", "/readyz") { _ in
            StubURLProtocol.json(503, ["status": "not_ready", "checks": [
                "postgres": ["status": "ok", "required": true],
                "redis": ["status": "failed", "required": true, "reason": "probe_failed"],
                "migration": ["status": "ok", "required": true],
                "hatchet": ["status": "disabled", "required": false, "reason": "health_check_disabled"],
                "model_gateway": ["status": "unchecked", "required": false],
                "some_new_probe": ["status": "ok", "required": false],
            ]])
        }
        let settings = store()
        await settings.loadReadiness()

        let report = settings.readiness
        XCTAssertNotNil(report, "a 503 carries the report and is not an error")
        XCTAssertNil(settings.notice)
        XCTAssertEqual(report?.ready, false)
        XCTAssertEqual(report?.checks.map(\.label), ["Records", "Records are up to date", "Live updates", "Background work", "Your AI", "Some New Probe"])
        XCTAssertEqual(report?.checks.map(\.statusLabel), ["Working", "Working", "Not working", "Not in use", "Not checked", "Working"])
        XCTAssertEqual(report?.checks.first { $0.id == "hatchet" }?.required, false)
    }

    func testReadinessReadyIsPlainToo() async {
        StubURLProtocol.on("GET", "/readyz") { _ in
            StubURLProtocol.json(200, ["status": "ready", "checks": ["postgres": ["status": "ok", "required": true]]])
        }
        let settings = store()
        await settings.loadReadiness()
        XCTAssertEqual(settings.readiness?.ready, true)
        XCTAssertEqual(settings.readiness?.checks.map(\.label), ["Records"])
    }

    // MARK: Account deletion

    func testDeleteAccountNeverReachesTheNetworkWhileUnavailable() async {
        XCTAssertFalse(BoltrigEnvironment.accountDeletionAvailable)
        let session = session()
        let settings = store(session: session)
        await settings.deleteAccount(password: "correct horse battery")

        XCTAssertTrue(StubURLProtocol.requests.isEmpty, "no request of any kind")
        XCTAssertEqual(settings.notice, "Deleting your account from the app is not available yet. Ask support and it will be done for you.")
        XCTAssertNotNil(vault.stored, "still signed in")
    }

    // MARK: Preview workspace

    func testPreviewStoreWritesNothingAndShowsEmptyStates() async {
        let settings = AccountSettingsStore(client: nil, account: Account.preview, session: nil)
        var next = settings.appearance
        next.theme = .light
        await settings.saveAppearance(next)
        await settings.loadArchived()
        await settings.loadSessions()
        await settings.loadSpending()
        let archived = await settings.archive(id: "preview-contract")

        XCTAssertTrue(settings.isPreview)
        XCTAssertEqual(settings.appearance.theme, .light)
        XCTAssertFalse(archived)
        XCTAssertEqual(settings.notice, "Archiving is not available in the preview workspace.")
        XCTAssertTrue(settings.archived.isEmpty && settings.sessions.isEmpty && settings.budgets.isEmpty)
        XCTAssertTrue(StubURLProtocol.requests.isEmpty)
    }
}
