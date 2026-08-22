import XCTest
@testable import Boltrig

final class ClientAndParsingTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
    }

    private func client(_ authorization: Authorization = .accessToken("boltrig_pat_x")) -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: authorization,
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    func testInstanceAddressParsing() {
        XCTAssertEqual(InstanceAddress.parse("dev.boltrig.ai")?.absoluteString, "https://dev.boltrig.ai")
        XCTAssertEqual(InstanceAddress.parse(" https://My-Box.local:8443/console?x=1 ")?.absoluteString, "https://my-box.local:8443")
        XCTAssertNil(InstanceAddress.parse("http://plain.example.com"), "plain http is refused")
        XCTAssertNil(InstanceAddress.parse(""))
        XCTAssertNil(InstanceAddress.parse("not a url at all ://"))
    }

    func testErrorMappingReadsBothEnvelopes() {
        let clamp = BoltrigClient.mapError(status: 403, data: #"{"detail":"password_change_required"}"#.data(using: .utf8)!)
        XCTAssertEqual(clamp.kind, .passwordChangeRequired)
        let enrol = BoltrigClient.mapError(status: 403, data: #"{"detail":"two_factor_enrollment_required"}"#.data(using: .utf8)!)
        XCTAssertEqual(enrol.kind, .twoFactorEnrolmentRequired)
        XCTAssertEqual(BoltrigClient.mapError(status: 429, data: Data()).kind, .throttled)
        XCTAssertEqual(BoltrigClient.mapError(status: 401, data: Data()).kind, .unauthenticated)
        let rejected = BoltrigClient.mapError(status: 400, data: #"{"status":"error","reason":"name is required"}"#.data(using: .utf8)!)
        XCTAssertEqual(rejected.kind, .rejected(reason: "name is required"))
        XCTAssertEqual(rejected.errorDescription, "Name is required.")
        let wrongPassword = BoltrigClient.mapError(status: 401, data: #"{"status":"error","reason":"invalid email or password"}"#.data(using: .utf8)!)
        XCTAssertEqual(wrongPassword.kind, .rejected(reason: "invalid email or password"))
        let deadToken = BoltrigClient.mapError(status: 401, data: #"{"detail":"invalid or expired access token"}"#.data(using: .utf8)!)
        XCTAssertEqual(deadToken.kind, .unauthenticated)
        XCTAssertEqual(BoltrigClient.mapError(status: 503, data: Data()).kind, .server(status: 503))
    }

    func testSignInOutcomeDecoding() throws {
        let twoFactor = try BoltrigClient.decodeSignIn(#"{"status":"2fa_required","challenge_token":"abc"}"#.data(using: .utf8)!)
        XCTAssertEqual(twoFactor, .twoFactorRequired(challengeToken: "abc"))
        let enrol = try BoltrigClient.decodeSignIn(#"{"status":"2fa_enrollment_required","csrf_token":"c","user":{"id":"u","email":"e@x","role":"r"}}"#.data(using: .utf8)!)
        XCTAssertEqual(enrol, .twoFactorEnrolmentRequired(csrfToken: "c", user: SignedInUser(id: "u", email: "e@x", role: "r")))
        XCTAssertThrowsError(try BoltrigClient.decodeSignIn(#"{"status":"weird"}"#.data(using: .utf8)!))
    }

    func testAccountDecodingReadsTheSettingsBag() throws {
        let data = try JSONSerialization.data(withJSONObject: Fixtures.settings)
        let account = try Account.decode(data)
        XCTAssertEqual(account.email, "ada@example.com")
        XCTAssertEqual(account.initials, "AL")
        XCTAssertEqual(account.activeWorkspaceID, "ws1")
        XCTAssertTrue(account.onboardingComplete)
        XCTAssertEqual(account.characterID, "familiar")
        XCTAssertEqual(account.companionPresence, .familiar)

        var fresh = Fixtures.settings
        fresh["settings"] = [:]
        fresh["profile"] = ["id": "u2", "email": "grace.hopper@example.com", "display_name": ""]
        let bare = try Account.decode(try JSONSerialization.data(withJSONObject: fresh))
        XCTAssertFalse(bare.onboardingComplete)
        XCTAssertNil(bare.characterID)
        XCTAssertEqual(bare.companionPresence, .unset)
        XCTAssertTrue(bare.companionPresence.needsAdoption)
        XCTAssertEqual(CompanionPresence(characterID: "another-character"), .other)
        XCTAssertEqual(CompanionPresence(characterID: "familiar"), .familiar)
        XCTAssertEqual(bare.nameForDisplay, "grace.hopper@example.com")
        XCTAssertEqual(bare.initials, "GH")
    }

    func testSSEParserJoinsDataLinesAndIgnoresOtherFields() {
        var parser = SSEFrameParser()
        XCTAssertNil(parser.consume(line: ": keep-alive"))
        XCTAssertNil(parser.consume(line: "data: {\"type\":\"text_delta\","))
        XCTAssertNil(parser.consume(line: "data: \"delta\":\"hi\"}"))
        let frame = parser.consume(line: "")
        XCTAssertEqual(frame?["type"] as? String, "text_delta")
        XCTAssertEqual(frame?["delta"] as? String, "hi")
        XCTAssertNil(parser.consume(line: "data: not json"))
        XCTAssertEqual(parser.flush()?["type"] as? String, "malformed_event")
        XCTAssertNil(parser.flush())
    }

    func testChatEventMapping() {
        XCTAssertEqual(ChatEvent.from(json: ["type": "text_delta", "delta": "a", "degraded": true]), .textDelta("a", degraded: true))
        XCTAssertEqual(ChatEvent.from(json: ["type": "hitl", "hitl_request_id": "h1", "question": "ok?"]), .needsYou(requestID: "h1", question: "ok?"))
        XCTAssertEqual(ChatEvent.from(json: ["type": "message_end", "run_id": "r1"]), .messageEnd(runID: "r1"))
        XCTAssertEqual(ChatEvent.from(json: ["type": "display_object"]), .other(type: "display_object"))
        XCTAssertEqual(ChatEvent.from(json: [:]), .other(type: "unknown"))
    }

    func testStreamChatYieldsEventsInOrder() async throws {
        let body = """
        data: {"type":"message_start","run_id":"r1","conversation_id":"c1"}

        data: {"type":"text_delta","delta":"Hello"}

        data: {"type":"text_delta","delta":", world"}

        data: {"type":"heartbeat"}

        data: {"type":"message_end","run_id":"r1"}

        """
        StubURLProtocol.on("POST", "/v1/chat") { _ in
            StubURLProtocol.Answer(status: 200, body: body.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        var events: [ChatEvent] = []
        for try await event in client().streamChat(message: "hi", conversationID: nil, idempotencyKey: "k") {
            events.append(event)
        }
        XCTAssertEqual(events, [
            .messageStart(runID: "r1", conversationID: "c1"),
            .textDelta("Hello", degraded: false),
            .textDelta(", world", degraded: false),
            .heartbeat,
            .messageEnd(runID: "r1"),
        ])
        let request = try XCTUnwrap(StubURLProtocol.recorded("POST", "/v1/chat").first)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "text/event-stream")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer boltrig_pat_x")
        let sent = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.body(of: request)) as? [String: Any])
        XCTAssertEqual(sent["message"] as? String, "hi")
        XCTAssertEqual(sent["idempotency_key"] as? String, "k")
        XCTAssertEqual((sent["attachments"] as? [Any])?.count, 0)
    }

    func testStreamChatReportsAQueuedTurn() async throws {
        StubURLProtocol.on("POST", "/v1/chat") { _ in
            StubURLProtocol.json(202, ["status": "queued", "conversation_id": "c9", "message_id": "m", "run_id": "r", "queued_run_id": "q", "agent_address": "a"])
        }
        var events: [ChatEvent] = []
        for try await event in client().streamChat(message: "later", conversationID: "c9", idempotencyKey: "k2") {
            events.append(event)
        }
        XCTAssertEqual(events, [.queued(conversationID: "c9")])
    }

    func testStreamChatSurfacesAnHTTPFailureBeforeTheStream() async {
        StubURLProtocol.on("POST", "/v1/chat") { _ in StubURLProtocol.json(401, ["detail": "no session"]) }
        do {
            for try await _ in client().streamChat(message: "x", conversationID: nil, idempotencyKey: "k3") {}
            XCTFail("expected a thrown error")
        } catch let error as BoltrigError {
            XCTAssertEqual(error.kind, .unauthenticated)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testConversationsDecodeTheServerShape() async throws {
        StubURLProtocol.on("GET", "/v1/conversations") { _ in
            StubURLProtocol.json(200, ["conversations": [
                ["id": "c1", "agent_address": "a", "workspace_id": "w", "title": "Briefing", "status": "open",
                 "updated_at": "2026-08-22T07:00:00+00:00", "working": true, "origin": "user", "source_ref": NSNull(),
                 "source_run_id": NSNull(), "companion_id": NSNull()],
                ["id": "c2", "title": "Older", "status": "closed", "updated_at": "2026-08-21T07:00:00+00:00", "working": false],
            ]])
        }
        let rows = try await client().conversations()
        XCTAssertEqual(rows.map(\.id), ["c1", "c2"])
        XCTAssertTrue(rows[0].isWorking)
        XCTAssertFalse(rows[1].isWorking)
    }

    func testApprovalsDecodeAndHeadings() async throws {
        StubURLProtocol.on("GET", "/v1/hitl") { _ in
            StubURLProtocol.json(200, ["requests": [
                ["id": "h1", "type": "approval", "urgency": "normal", "question": "Send it?", "context": "", "options": ["approve", "decline"],
                 "work_item_id": NSNull(), "status": "pending", "run_id": "r1", "verb": "mail.send", "requested_by": "u1",
                 "requested_on_behalf_of": NSNull(), "inputs": NSNull(), "secure": false, "secure_purpose": NSNull()],
                ["id": "h2", "type": "question", "question": "Which one?", "verb": NSNull()],
            ]])
        }
        let rows = try await client().approvals()
        XCTAssertEqual(rows[0].heading, "mail.send")
        XCTAssertEqual(rows[1].heading, "A question for you")
        XCTAssertEqual(rows[0].runID, "r1")
    }

    func testKeychainRoundTrip() throws {
        let account = "test-\(UUID().uuidString)"
        do {
            try Keychain.setString("first", for: account)
        } catch let error as Keychain.KeychainError where error.status == -34018 {
            // errSecMissingEntitlement: the host app was built unsigned (CODE_SIGNING_ALLOWED=NO).
            // The Keychain needs a signed host even on the simulator; run the tests without that flag.
            throw XCTSkip("Keychain needs a signed host app; build with code signing on to run this test.")
        }
        XCTAssertEqual(try Keychain.string(for: account), "first")
        try Keychain.setString("second", for: account)
        XCTAssertEqual(try Keychain.string(for: account), "second")
        try Keychain.remove(account)
        XCTAssertNil(try Keychain.string(for: account))
        try Keychain.remove(account)
    }
}
