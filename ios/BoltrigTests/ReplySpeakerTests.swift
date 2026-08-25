import XCTest
@testable import Boltrig

final class FakePlayer: AudioPlaying {
    var played: [Data] = []
    var stops = 0
    var isPlaying = false
    var level: Double = 0.6
    var onFinished: (() -> Void)?
    var failOnPlay = false

    func play(_ data: Data) throws {
        if failOnPlay { throw NSError(domain: "fake", code: 1) }
        played.append(data)
        isPlaying = true
    }

    func stop() {
        stops += 1
        isPlaying = false
    }

    func finish() {
        isPlaying = false
        onFinished?()
    }
}

@MainActor
final class ReplySpeakerTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
    }

    private func client() -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_x"),
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    private func account(readReplies: Bool, overrides: [String: String] = [:]) -> Account {
        Account(id: "u1", email: "ada@example.com", displayName: "Ada", role: "member", activeWorkspaceID: nil,
                onboardingComplete: true, characterID: "familiar", readReplies: readReplies, voiceOverrides: overrides)
    }

    private func capabilities(provider: String?) -> CapabilitiesSnapshot {
        guard let provider else { return CapabilitiesSnapshot(verbs: []) }
        return CapabilitiesSnapshot(verbs: [.init(id: "voice.speak", bindingTargetType: "adapter", bindingTargetRef: provider)])
    }

    func testResolutionFollowsTheSettingTheProviderAndTheVoiceRules() {
        XCTAssertFalse(SpeechResolution.resolve(account: account(readReplies: false), capabilities: capabilities(provider: "pocket-voice")).canSpeak)
        XCTAssertFalse(SpeechResolution.resolve(account: account(readReplies: true), capabilities: capabilities(provider: nil)).canSpeak)
        XCTAssertFalse(SpeechResolution.resolve(account: account(readReplies: true), capabilities: nil).canSpeak)
        let local = SpeechResolution.resolve(account: account(readReplies: true), capabilities: capabilities(provider: "pocket-voice"))
        XCTAssertEqual(local.voiceID, "familiar")
        let overridden = SpeechResolution.resolve(account: account(readReplies: true, overrides: ["familiar": "my.voice-2"]), capabilities: capabilities(provider: "pocket-voice"))
        XCTAssertEqual(overridden.voiceID, "my.voice-2")
        let badOverride = SpeechResolution.resolve(account: account(readReplies: true, overrides: ["familiar": "not valid!"]), capabilities: capabilities(provider: "pocket-voice"))
        XCTAssertEqual(badOverride.voiceID, "familiar", "an invalid override falls back to Familiar's own voice")
        let fish = SpeechResolution.resolve(account: account(readReplies: true, overrides: ["familiar": "ignored"]), capabilities: capabilities(provider: "fish"))
        XCTAssertEqual(fish.voiceID, "c8f64deb39914cfca7f47ccfc3bca82f", "overrides apply to the local provider only")
        XCTAssertNil(SpeechResolution.resolve(account: account(readReplies: true), capabilities: capabilities(provider: "unknown-provider")).voiceID)
    }

    func testSpeechTextReducesMarkdownLikeTheWeb() {
        let text = SpeechResolution.speechText("# Title\n\nHere is **bold** and _soft_ and `code` and [a link](https://x) and ![img](y).\n\n```swift\nlet x = 1\n```\n\n- one\n- two\n> quoted")
        XCTAssertEqual(text, "Title Here is bold and soft and code and a link and img. Code omitted. one two quoted")
        XCTAssertEqual(SpeechResolution.speechText(String(repeating: "a", count: 20_000)).count, 15_000)
    }

    func testSpeaksOncePerRunWithTheExactRequest() async throws {
        let wav = Data([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0])
        StubURLProtocol.on("POST", "/v1/invoke") { _ in
            StubURLProtocol.json(200, ["status": "ok", "output": ["audio_b64": wav.base64EncodedString(), "content_type": "audio/wav", "voice": "familiar", "chars": 5]])
        }
        let player = FakePlayer()
        let speaker = ReplySpeaker(client: client(), player: player)
        speaker.resolution = SpeechResolution(enabled: true, provider: "pocket-voice", voiceID: "familiar")
        await speaker.speak(runID: "r1", markdown: "**Hello** there")
        XCTAssertEqual(player.played, [wav])
        XCTAssertTrue(speaker.isSpeaking)
        let request = try XCTUnwrap(StubURLProtocol.recorded("POST", "/v1/invoke").first)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.body(of: request)) as? [String: Any])
        XCTAssertEqual(body["noun"] as? String, "voice")
        XCTAssertEqual(body["verb"] as? String, "voice.speak")
        XCTAssertEqual((body["params"] as? [String: Any])?["text"] as? String, "Hello there")
        XCTAssertEqual((body["params"] as? [String: Any])?["voice"] as? String, "familiar")
        await speaker.speak(runID: "r1", markdown: "**Hello** there")
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/invoke").count, 1, "a run is spoken once")
        player.finish()
        try? await Task.sleep(nanoseconds: 50_000_000)
        XCTAssertFalse(speaker.isSpeaking)
    }

    func testFailuresAreSilent() async {
        StubURLProtocol.on("POST", "/v1/invoke") { _ in StubURLProtocol.json(202, ["status": "pending_human", "hitl_request_id": "h1"]) }
        let player = FakePlayer()
        let speaker = ReplySpeaker(client: client(), player: player)
        speaker.resolution = SpeechResolution(enabled: true, provider: "pocket-voice", voiceID: "familiar")
        await speaker.speak(runID: "r1", markdown: "hello")
        XCTAssertTrue(player.played.isEmpty)
        XCTAssertFalse(speaker.isSpeaking)
        StubURLProtocol.on("POST", "/v1/invoke") { _ in StubURLProtocol.json(200, ["status": "ok", "output": ["audio_b64": "%%%notbase64", "content_type": "audio/wav"]]) }
        await speaker.speak(runID: "r2", markdown: "hello")
        XCTAssertTrue(player.played.isEmpty)
        StubURLProtocol.on("POST", "/v1/invoke") { _ in StubURLProtocol.json(403, ["status": "denied", "reason": "not allowed"]) }
        await speaker.speak(runID: "r3", markdown: "hello")
        XCTAssertTrue(player.played.isEmpty)
        speaker.resolution = .silent
        StubURLProtocol.on("POST", "/v1/invoke") { _ in StubURLProtocol.json(200, ["status": "ok", "output": ["audio_b64": Data([1, 2, 3]).base64EncodedString()]]) }
        await speaker.speak(runID: "r4", markdown: "hello")
        XCTAssertTrue(StubURLProtocol.recorded("POST", "/v1/invoke").filter { _ in true }.count == 3, "nothing is requested when reading aloud is off")
    }

    func testStopEndsSpeechAndANewTurnStopsTheOldOne() async {
        let wav = Data([1, 2, 3, 4])
        StubURLProtocol.on("POST", "/v1/invoke") { _ in StubURLProtocol.json(200, ["status": "ok", "output": ["audio_b64": wav.base64EncodedString()]]) }
        let player = FakePlayer()
        let speaker = ReplySpeaker(client: client(), player: player)
        speaker.resolution = SpeechResolution(enabled: true, provider: "pocket-voice", voiceID: "familiar")
        await speaker.speak(runID: "r1", markdown: "one")
        XCTAssertTrue(speaker.isSpeaking)
        speaker.stop()
        XCTAssertEqual(player.stops, 1)
        XCTAssertFalse(speaker.isSpeaking)
        XCTAssertEqual(speaker.level, 0)
    }

    func testWorkspaceWiresTheSpeakerIntoTheChat() async throws {
        let frames = """
        data: {"type":"message_start","run_id":"r9","conversation_id":"c1"}

        data: {"type":"text_delta","delta":"Done."}

        data: {"type":"message_end","run_id":"r9"}

        """
        StubURLProtocol.on("POST", "/v1/chat") { _ in
            StubURLProtocol.Answer(status: 200, body: frames.data(using: .utf8)!, headers: ["Content-Type": "text/event-stream"])
        }
        StubURLProtocol.on("POST", "/v1/invoke") { _ in StubURLProtocol.json(200, ["status": "ok", "output": ["audio_b64": Data([9, 9]).base64EncodedString()]]) }
        let player = FakePlayer()
        let store = AppStore(client: client(), account: account(readReplies: true), player: player)
        store.speaker.resolution = SpeechResolution(enabled: true, provider: "pocket-voice", voiceID: "familiar")
        await store.chat.sendMessage("go")
        try? await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(player.played.count, 1, "the finished reply is spoken once")
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/invoke").count, 1)
        XCTAssertTrue(store.chat.speaking)
        XCTAssertEqual(store.chat.presenceMode, .speaking)
    }
}
