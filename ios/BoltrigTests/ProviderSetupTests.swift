import XCTest
@testable import Boltrig

/// The provider state machine: one press, key cleared before the await, approvals answered
/// in the same press, the gateway read back, and every sentence the person sees.
@MainActor
final class ProviderSetupTests: XCTestCase {
    private var client: BoltrigClient!

    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
        client = OnboardingFixtures.client()
    }

    private func setup(role: String = "member", modality: AIModality = .text) -> ProviderSetupStore {
        ProviderSetupStore(client: client, account: OnboardingFixtures.account(role: role), modality: modality,
                           catalogue: OnboardingFixtures.smallCatalogue)
    }

    /// A typed provider ready to submit: key present, model chosen.
    private func readySetup() async -> ProviderSetupStore {
        let store = setup()
        OnboardingFixtures.stubKeys()
        await store.load()
        XCTAssertTrue(store.canAddKey)
        store.selectProvider("openai")
        store.model = "openai/gpt-4.1"
        store.apiKey = "sk-test"
        return store
    }

    private func firstPUTBody() throws -> [String: Any] {
        try OnboardingFixtures.sentJSON(try XCTUnwrap(StubURLProtocol.recorded("PUT", "/v1/ai-keys").first))
    }

    func testProviderClearsTheKeyBeforeAwaitingAndSendsItOnce() async throws {
        let store = await readySetup()
        let keyAtSend = CapturedValue<String>()
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in
            // Runs on the loader's thread while the store awaits the answer: the field must already be empty.
            keyAtSend.value = DispatchQueue.main.sync { MainActor.assumeIsolated { store.apiKey } }
            return StubURLProtocol.json(200, ["status": "ok", "proposal_id": "akp_0"])
        }
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true)])

        let ok = await store.complete()

        XCTAssertTrue(ok)
        XCTAssertEqual(keyAtSend.value, "")
        XCTAssertEqual(store.apiKey, "")
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.connected)
        let body = try firstPUTBody()
        XCTAssertEqual(body["api_key"] as? String, "sk-test")
        XCTAssertEqual(body["level"] as? String, "user")
        XCTAssertEqual(body["provider"] as? String, "openai")
        XCTAssertEqual(body["model"] as? String, "openai/gpt-4.1")
        XCTAssertEqual(body["modality"] as? String, "text")
        XCTAssertNil(body["base_url"], "a native provider submits no address")
        XCTAssertEqual(StubURLProtocol.recorded("PUT", "/v1/ai-keys").count, 1)
    }

    func testPendingHumanIsApprovedInTheSamePress() async throws {
        let store = await readySetup()
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in
            StubURLProtocol.json(202, ["status": "pending_human", "reason": "This connection is waiting for an administrator's approval.",
                                       "proposal": OnboardingFixtures.proposal])
        }
        StubURLProtocol.on("POST", "/v1/ai-keys/proposals/akp_1/approve") { _ in
            StubURLProtocol.json(200, ["status": "ok", "proposal_id": "akp_1", "provider": "openai", "model": "openai/gpt-4.1"])
        }
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true)])

        let ok = await store.complete()

        XCTAssertTrue(ok)
        XCTAssertNil(store.proposal)
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.connected)
        XCTAssertEqual(StubURLProtocol.recorded("PUT", "/v1/ai-keys").count, 1)
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/ai-keys/proposals/akp_1/approve").count, 1)
    }

    func testAdministratorPendingIsCachedAndTheNextPressApprovesWithoutResubmitting() async throws {
        let store = await readySetup()
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in
            StubURLProtocol.json(202, ["status": "pending_human", "proposal": OnboardingFixtures.proposal])
        }
        StubURLProtocol.on("POST", "/v1/ai-keys/proposals/akp_1/approve") { _ in
            StubURLProtocol.json(202, ["status": "pending", "reason": "This connection is waiting for an administrator's approval.",
                                       "proposal": OnboardingFixtures.proposal])
        }

        let first = await store.complete()
        XCTAssertFalse(first)
        XCTAssertEqual(store.proposal?.id, "akp_1")
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.waiting)
        XCTAssertFalse(store.busy)

        StubURLProtocol.on("POST", "/v1/ai-keys/proposals/akp_1/approve") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true)])
        let second = await store.complete()
        XCTAssertTrue(second)
        XCTAssertNil(store.proposal)
        XCTAssertEqual(StubURLProtocol.recorded("PUT", "/v1/ai-keys").count, 1, "the key is never submitted twice")
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/ai-keys/proposals/akp_1/approve").count, 2)
    }

    func testDeadProposalIsDroppedWithTheServersSentence() async throws {
        let store = await readySetup()
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in
            StubURLProtocol.json(202, ["status": "pending_human", "proposal": OnboardingFixtures.proposal])
        }
        StubURLProtocol.on("POST", "/v1/ai-keys/proposals/akp_1/approve") { _ in
            StubURLProtocol.json(409, ["status": "expired", "reason": "This request expired before it finished. Submit the provider again.",
                                       "proposal": OnboardingFixtures.proposal])
        }
        let ok = await store.complete()
        XCTAssertFalse(ok)
        XCTAssertNil(store.proposal, "a dead request is not held for the next press")
        XCTAssertEqual(store.message, "This request expired before it finished. Submit the provider again.")
    }

    func testGatewayNotReadyHoldsTheStep() async throws {
        let store = await readySetup()
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: false)])

        let ok = await store.complete()

        XCTAssertFalse(ok)
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.savedNotAnswering)
        XCTAssertEqual(store.readiness?.keys.count, 1)
    }

    func testUnreachableReReadPasses() async throws {
        let store = await readySetup()
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        StubURLProtocol.on("GET", "/v1/ai-keys") { _ in StubURLProtocol.Answer(status: 0, body: Data(), fail: true) }

        let ok = await store.complete()

        XCTAssertTrue(ok)
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.savedUnconfirmed)
    }

    func testManagedOrganisationPassesWithoutSubmitting() async throws {
        let store = setup(role: "member")
        OnboardingFixtures.stubKeys(allowOwn: false)
        await store.load()
        XCTAssertFalse(store.canAddKey)
        XCTAssertEqual(store.level, "org")

        let ok = await store.complete()

        XCTAssertTrue(ok)
        XCTAssertTrue(StubURLProtocol.recorded("PUT", "/v1/ai-keys").isEmpty)
        XCTAssertTrue(StubURLProtocol.recorded("POST", "/v1/ai-keys/activate").isEmpty)

        let owner = setup(role: "owner")
        await owner.load()
        XCTAssertTrue(owner.canAddKey, "an administrator saves at organisation level when own keys are off")
        XCTAssertEqual(owner.level, "org")
    }

    func testSelfHostedSubmitsWithoutAKey() async throws {
        let store = setup()
        OnboardingFixtures.stubKeys()
        await store.load()
        store.selectProvider("ollama")
        XCTAssertTrue(store.keyOptional)
        XCTAssertTrue(store.needsAddress)
        store.setTypedModelName("x")
        XCTAssertEqual(store.model, "ollama/x")
        XCTAssertEqual(store.typedModelName, "x")
        store.baseURL = "http://mac-mini-m1:11434"
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true, provider: "ollama", model: "ollama/x:latest")])

        let ok = await store.complete()

        XCTAssertTrue(ok)
        let body = try firstPUTBody()
        XCTAssertEqual(body["api_key"] as? String, "")
        XCTAssertEqual(body["provider"] as? String, "ollama")
        XCTAssertEqual(body["model"] as? String, "ollama/x")
        XCTAssertEqual(body["base_url"] as? String, "http://mac-mini-m1:11434")
    }

    func testNonNativeProviderSubmitsItsPublishedAddress() async throws {
        let store = setup()
        OnboardingFixtures.stubKeys()
        await store.load()
        store.selectProvider("deepseek")
        XCTAssertFalse(store.needsAddress)
        store.model = "deepseek/deepseek-chat"
        store.apiKey = "sk-deep"
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true, provider: "deepseek", model: "deepseek/deepseek-chat")])
        let ok = await store.complete()
        XCTAssertTrue(ok)
        XCTAssertEqual(try firstPUTBody()["base_url"] as? String, "https://api.deepseek.com")
    }

    func testServerReasonIsShownVerbatim() async throws {
        let store = await readySetup()
        let sentence = "your provider did not answer at that address; check the URL (self-hosted servers are usually http://, not https://), then enter the key and address again"
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(503, ["status": "unavailable", "reason": sentence]) }

        let ok = await store.complete()

        XCTAssertFalse(ok)
        XCTAssertEqual(store.message, "Your provider did not answer at that address; check the URL (self-hosted servers are usually http://, not https://), then enter the key and address again.")
        XCTAssertEqual(store.apiKey, "", "the key is gone even when the server refuses")
        XCTAssertFalse(store.busy)
    }

    func testIncompleteInputSaysWhatIsMissingWithoutSubmitting() async throws {
        let store = setup()
        OnboardingFixtures.stubKeys()
        await store.load()
        store.selectProvider("openai")
        store.apiKey = "sk-test"
        let noModel = await store.complete()
        XCTAssertFalse(noModel)
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.incomplete)
        XCTAssertEqual(store.apiKey, "sk-test", "nothing was sent, so the key stays")

        store.apiKey = ""
        store.model = "openai/gpt-4.1"
        let noKey = await store.complete()
        XCTAssertFalse(noKey)
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.keyMissing)

        store.selectProvider("togetherai")
        store.model = "togetherai/llama-3"
        store.apiKey = "sk-t"
        XCTAssertTrue(store.needsAddress, "a non-native provider with no published address needs one typed")
        let noAddress = await store.complete()
        XCTAssertFalse(noAddress)
        XCTAssertEqual(store.message, ProviderSetupStore.Copy.incomplete)
        XCTAssertTrue(StubURLProtocol.recorded("PUT", "/v1/ai-keys").isEmpty)
    }

    func testExistingReadyKeyPassesAndAnUnreadyOneIsActivated() async throws {
        let ready = setup()
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true)])
        await ready.load()
        XCTAssertEqual(ready.existingKey?.modelLabel, "gpt-4.1")
        let passed = await ready.complete()
        XCTAssertTrue(passed)
        XCTAssertTrue(StubURLProtocol.recorded("POST", "/v1/ai-keys/activate").isEmpty)

        StubURLProtocol.reset()
        let unready = setup()
        let reads = CallCounter()
        StubURLProtocol.on("GET", "/v1/ai-keys") { _ in
            let ready = reads.next() > 1
            return StubURLProtocol.json(200, ["allow_own_ai_keys": true, "ai_keys": [OnboardingFixtures.keyRow(gatewayReady: ready)]])
        }
        StubURLProtocol.on("POST", "/v1/ai-keys/activate") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        await unready.load()
        let activated = await unready.complete()
        XCTAssertTrue(activated)
        let activate = try XCTUnwrap(StubURLProtocol.recorded("POST", "/v1/ai-keys/activate").first)
        let body = try OnboardingFixtures.sentJSON(activate)
        XCTAssertEqual(body["level"] as? String, "user")
        XCTAssertEqual(body["scope_id"] as? String, "u1")
        XCTAssertEqual(body["modality"] as? String, "text")
        XCTAssertEqual(unready.message, ProviderSetupStore.Copy.connected)
    }

    func testVisionStoreReadsOnlyItsOwnKey() async throws {
        let store = setup(modality: .vision)
        OnboardingFixtures.stubKeys(keys: [OnboardingFixtures.keyRow(gatewayReady: true, modality: "text"),
                                           OnboardingFixtures.keyRow(gatewayReady: false, modality: "vision")])
        await store.load()
        XCTAssertEqual(store.existingKey?.modality, "vision")
        XCTAssertEqual(store.existingKey?.gatewayReady, false)
    }
}
