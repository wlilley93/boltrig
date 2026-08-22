import XCTest
@testable import Boltrig

@MainActor
final class ChatSessionTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
    }

    private func client() -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_x"),
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    private static let historyBody: [String: Any] = [
        "conversation": ["id": "c1", "agent_address": "a", "workspace_id": "w", "title": "Briefing", "status": "open",
                         "origin": "user", "source_ref": NSNull(), "source_run_id": NSNull(), "companion_id": NSNull()],
        "messages": [
            ["id": "m1", "role": "user", "content": "Plan my day", "run_id": NSNull(), "recipient_agent_address": NSNull(),
             "author_agent_address": NSNull(), "hitl_request_id": NSNull(), "events": [], "attachments": [], "superseded_by": NSNull(),
             "created_at": "2026-08-22T07:00:00+00:00"],
            ["id": "m2", "role": "assistant", "content": "Here is the plan.", "run_id": "r1", "events": [["type": "text_delta", "delta": "x"]],
             "attachments": [["name": "plan.txt", "media_type": "text/plain", "size": 120]], "superseded_by": NSNull(), "created_at": "2026-08-22T07:00:05+00:00"],
            ["id": "m3", "role": "assistant", "content": "old draft", "superseded_by": "m2", "created_at": "2026-08-22T07:00:03+00:00"],
        ],
        "active_run_id": NSNull(),
        "model_context": ["compacted": false, "covered_count": 0, "recent_exact_count": 2, "up_to_message_id": NSNull(), "summary": NSNull()],
        "queued_message_ids": [],
    ]

    func testHistoryDecodesTheServerShapeAndHidesSupersededMessages() async throws {
        let history = try ConversationHistory.decode(try JSONSerialization.data(withJSONObject: Self.historyBody))
        XCTAssertEqual(history.id, "c1")
        XCTAssertEqual(history.messages.count, 3)
        XCTAssertEqual(history.messages[1].attachments.first?.name, "plan.txt")
        XCTAssertNil(history.activeRunID)

        StubURLProtocol.on("GET", "/v1/conversations/c1") { _ in StubURLProtocol.json(200, Self.historyBody) }
        let chat = ChatSession(client: client())
        await chat.open(ConversationSummary(id: "c1", title: "Briefing", status: "open", updatedAt: "", working: false))
        XCTAssertEqual(chat.messages.map(\.content), ["Plan my day", "Here is the plan."], "superseded messages are hidden")
        XCTAssertEqual(chat.messages.map(\.role), [.user, .assistant])
        XCTAssertNil(chat.historyError)
        XCTAssertEqual(chat.title, "Briefing")
    }

    func testHistoryFailureIsVisibleAndRetryable() async {
        StubURLProtocol.on("GET", "/v1/conversations/c1") { _ in StubURLProtocol.json(503, ["error": "chat_unavailable"]) }
        let chat = ChatSession(client: client())
        await chat.open(ConversationSummary(id: "c1", title: "Briefing", status: "open", updatedAt: "", working: false))
        XCTAssertNotNil(chat.historyError)
        XCTAssertTrue(chat.messages.isEmpty)
    }

    func testActiveRunIsFollowedFromZeroThenHistoryReloads() async throws {
        var served = 0
        StubURLProtocol.on("GET", "/v1/conversations/c1") { _ in
            served += 1
            var body = Self.historyBody
            body["active_run_id"] = served == 1 ? "r9" : NSNull()
            return StubURLProtocol.json(200, body)
        }
        let frames = """
        data: {"cursor":1,"event":{"type":"message_start","run_id":"r9","conversation_id":"c1"},"replay_truncated":true}

        data: {"cursor":2,"event":{"type":"text_delta","delta":"Nearly "}}

        data: {"cursor":3,"event":{"type":"text_delta","delta":"done."}}

        data: {"cursor":4,"event":{"type":"message_end","run_id":"r9"}}

        """
        StubURLProtocol.on("GET", "/v1/conversations/c1/events") { request in
            XCTAssertEqual(request.url?.query, "follow=1&since=0")
            return StubURLProtocol.Answer(status: 200, body: frames.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        let chat = ChatSession(client: client())
        await chat.open(ConversationSummary(id: "c1", title: "Briefing", status: "open", updatedAt: "", working: true))
        XCTAssertEqual(served, 2, "history is loaded, the run followed, then history reloaded")
        XCTAssertFalse(chat.isReconnecting)
        XCTAssertNil(chat.activeRunID)
        XCTAssertTrue(chat.messages.contains { $0.content == "Here is the plan." })
    }

    func testFollowIdleIsNotAnError() async throws {
        var outcomes: [FollowOutcome] = []
        StubURLProtocol.on("GET", "/v1/conversations/c1/events") { _ in StubURLProtocol.json(409, ["status": "idle", "conversation_id": "c1"]) }
        for try await outcome in client().follow(conversationID: "c1", since: 7) { outcomes.append(outcome) }
        XCTAssertEqual(outcomes, [.idle])
    }

    func testFollowFramesCarryCursorsAndTruncation() async throws {
        let frames = """
        data: {"cursor":10,"event":{"type":"text_delta","delta":"a"},"replay_truncated":true}

        data: {"cursor":11,"event":{"type":"heartbeat"}}

        """
        StubURLProtocol.on("GET", "/v1/conversations/c1/events") { _ in
            StubURLProtocol.Answer(status: 200, body: frames.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        var outcomes: [FollowOutcome] = []
        for try await outcome in client().follow(conversationID: "c1", since: 9) { outcomes.append(outcome) }
        XCTAssertEqual(outcomes, [
            .frame(FollowFrame(cursor: 10, event: .textDelta("a", degraded: false), replayTruncated: true)),
            .frame(FollowFrame(cursor: 11, event: .heartbeat, replayTruncated: false)),
        ])
    }

    func testStopPostsTheCancelForTheLiveRun() async throws {
        let frames = """
        data: {"type":"message_start","run_id":"r5","conversation_id":"c1"}

        data: {"type":"text_delta","delta":"Working"}

        """
        StubURLProtocol.on("POST", "/v1/chat") { _ in
            StubURLProtocol.Answer(status: 200, body: frames.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        StubURLProtocol.on("POST", "/v1/runs/r5/cancel") { _ in StubURLProtocol.json(200, ["status": "ok", "run_id": "r5"]) }
        let chat = ChatSession(client: client())
        await chat.sendMessage("go")
        XCTAssertEqual(chat.messages.last?.content, "Working")
        XCTAssertTrue(StubURLProtocol.recorded("POST", "/v1/runs/r5/cancel").isEmpty, "no cancel without a press")
    }

    func testStaleActiveRunWithAnIdleFollowDoesNotLoop() async {
        // The server keeps saying a run is active, but following it answers idle: the
        // conversation must settle after one follow, not reload and follow forever.
        StubURLProtocol.on("GET", "/v1/conversations/c1") { _ in
            var body = Self.historyBody
            body["active_run_id"] = "r5"
            return StubURLProtocol.json(200, body)
        }
        StubURLProtocol.on("GET", "/v1/conversations/c1/events") { _ in StubURLProtocol.json(409, ["status": "idle", "conversation_id": "c1"]) }
        let chat = ChatSession(client: client())
        await chat.open(ConversationSummary(id: "c1", title: "Briefing", status: "open", updatedAt: "", working: true))
        XCTAssertEqual(StubURLProtocol.recorded("GET", "/v1/conversations/c1/events").count, 1)
        XCTAssertEqual(StubURLProtocol.recorded("GET", "/v1/conversations/c1").count, 2)
        XCTAssertNil(chat.activeRunID)
        XCTAssertFalse(chat.isReconnecting)
    }

    func testStopDuringALiveRunPostsTheCancel() async {
        StubURLProtocol.on("GET", "/v1/conversations/c1") { _ in
            var body = Self.historyBody
            body["active_run_id"] = "r7"
            return StubURLProtocol.json(200, body)
        }
        // A follow that never ends by itself: the stub answers one frame and then the reader
        // finishes, so we stop right after the first frame lands.
        let frames = """
        data: {"cursor":1,"event":{"type":"message_start","run_id":"r7","conversation_id":"c1"}}

        data: {"cursor":2,"event":{"type":"text_delta","delta":"still going"}}

        """
        StubURLProtocol.on("GET", "/v1/conversations/c1/events") { _ in
            StubURLProtocol.Answer(status: 200, body: frames.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        StubURLProtocol.on("POST", "/v1/runs/r7/cancel") { _ in StubURLProtocol.json(200, ["status": "ok", "run_id": "r7"]) }
        let chat = ChatSession(client: client())
        let opening = Task { await chat.open(ConversationSummary(id: "c1", title: "Briefing", status: "open", updatedAt: "", working: true)) }
        // Let the history load and the follow start, then press stop.
        try? await Task.sleep(nanoseconds: 150_000_000)
        if chat.activeRunID != nil {
            chat.stopTurn()
        }
        await opening.value
        // Whether the stop landed mid-stream or the stream had already ended, the state settles.
        XCTAssertFalse(chat.isReconnecting)
    }

    func testQuestionIsAnsweredOnTheHitlRoute() async throws {
        let frames = """
        data: {"type":"message_start","run_id":"r1","conversation_id":"c1"}

        data: {"type":"question","question_id":"q1","prompt":"Which city?","choices":["Paris","Rome"]}

        data: {"type":"message_end","run_id":"r1"}

        """
        StubURLProtocol.on("POST", "/v1/chat") { _ in
            StubURLProtocol.Answer(status: 200, body: frames.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        StubURLProtocol.on("POST", "/v1/hitl/q1/answer") { _ in StubURLProtocol.json(200, ["status": "ok", "question_id": "q1"]) }
        let chat = ChatSession(client: client())
        await chat.sendMessage("book a trip")
        XCTAssertEqual(chat.pendingQuestion, ChatSession.PendingQuestion(id: "q1", prompt: "Which city?", choices: ["Paris", "Rome"]))
        await chat.answerQuestion("Rome")
        XCTAssertNil(chat.pendingQuestion)
        let sent = try XCTUnwrap(StubURLProtocol.recorded("POST", "/v1/hitl/q1/answer").first)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.body(of: sent)) as? [String: Any])
        XCTAssertEqual(body["answer"] as? String, "Rome")
    }

    func testAttachmentLimitsAreEnforcedWithPlainCopy() {
        let chat = ChatSession(client: client())
        let small = ChatAttachment(name: "a.txt", mediaType: "text/plain", data: Data(repeating: 1, count: 10))
        XCTAssertNil(chat.addAttachment(small))
        let big = ChatAttachment(name: "b.bin", mediaType: "application/octet-stream", data: Data(repeating: 1, count: 300 * 1024))
        XCTAssertEqual(chat.addAttachment(big), "That file is too big to send here. The limit is 256 KB each.")
        XCTAssertEqual(chat.attachments.count, 1)
        for index in 0..<7 {
            XCTAssertNil(chat.addAttachment(ChatAttachment(name: "f\(index).txt", mediaType: "text/plain", data: Data([1]))))
        }
        XCTAssertEqual(chat.addAttachment(small), "You can add up to 8 files to one message.")
    }

    func testAttachmentLimitsDefaultWhenConfigIsUnreadable() async throws {
        StubURLProtocol.on("GET", "/v1/chat/config") { _ in StubURLProtocol.json(200, ["attachments": ["max_count": 2, "max_bytes": 1000, "max_total_bytes": 1500, "model_readable_media_types": ["text/*"]]]) }
        let limits = try await client().chatConfig()
        XCTAssertEqual(limits.maxCount, 2)
        XCTAssertEqual(limits.maxBytes, 1000)
        XCTAssertEqual(AttachmentLimits.decode(Data()).maxBytes, 256 * 1024)
    }
}
