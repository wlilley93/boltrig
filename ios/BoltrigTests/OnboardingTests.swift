import XCTest
@testable import Boltrig

/// First-run setup around the provider machine: finishing in order, the name rule, the
/// client's outcome mapping, the bundled catalogue and the root gate.
@MainActor
final class OnboardingTests: XCTestCase {
    private var client: BoltrigClient!

    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
        client = OnboardingFixtures.client()
    }

    private func store(name: String = "Ada Lovelace") -> OnboardingStore {
        OnboardingStore(client: client, account: OnboardingFixtures.account(name: name), catalogue: OnboardingFixtures.smallCatalogue)
    }

    // MARK: Finishing

    func testFinishWritesProfileThenSettingsOnceUnderConcurrentPresses() async throws {
        OnboardingFixtures.stubFinish()
        let store = store(name: "  Ada   Lovelace ")
        XCTAssertEqual(store.step, .provider, "a named account starts at Provider")

        async let first = store.finish()
        async let second = store.finish()
        let results = await [first, second]

        XCTAssertEqual(results.filter { $0 }.count, 1, "exactly one press finishes")
        XCTAssertEqual(store.step, .ready)
        XCTAssertEqual(StubURLProtocol.recorded("PATCH", "/v1/me/profile").count, 1)
        XCTAssertEqual(StubURLProtocol.recorded("PUT", "/v1/me/settings").count, 1)
        let order = StubURLProtocol.requests.compactMap(\.httpMethod)
        let patchIndex = try XCTUnwrap(order.firstIndex(of: "PATCH"))
        let putIndex = try XCTUnwrap(order.firstIndex(of: "PUT"))
        XCTAssertLessThan(patchIndex, putIndex, "the name is saved before the settings")
        let profile = try OnboardingFixtures.sentJSON(try XCTUnwrap(StubURLProtocol.recorded("PATCH", "/v1/me/profile").first))
        XCTAssertEqual(profile["display_name"] as? String, "Ada Lovelace")
        let settings = try OnboardingFixtures.sentJSON(try XCTUnwrap(StubURLProtocol.recorded("PUT", "/v1/me/settings").first))
        let values = try XCTUnwrap(settings["settings"] as? [String: Any])
        XCTAssertEqual(values["agent.character"] as? String, "familiar")
        XCTAssertEqual(values["setup.onboarding_version"] as? Int, 1)
        XCTAssertEqual(StubURLProtocol.recorded("POST", "/v1/familiar/emotion/adopted").count, 1)
    }

    func testFinishFailureStaysOnTheStep() async throws {
        StubURLProtocol.on("PATCH", "/v1/me/profile") { _ in StubURLProtocol.json(500, ["detail": "Internal Server Error"]) }
        let store = store()

        let failed = await store.finish()

        XCTAssertFalse(failed)
        XCTAssertEqual(store.step, .provider)
        XCTAssertEqual(store.finishMessage, OnboardingStore.Copy.saveFailed)
        XCTAssertFalse(store.isFinishing)
        XCTAssertTrue(StubURLProtocol.recorded("PUT", "/v1/me/settings").isEmpty, "settings are not written when the name was not saved")

        OnboardingFixtures.stubFinish()
        let retried = await store.finish()
        XCTAssertTrue(retried, "the next press succeeds")
        XCTAssertEqual(store.step, .ready)
        XCTAssertNil(store.finishMessage)
    }

    func testFinishReturnsToTheNameStepWhenTheServerRefusesTheName() async throws {
        StubURLProtocol.on("PATCH", "/v1/me/profile") { _ in
            StubURLProtocol.json(400, ["status": "error", "reason": "display_name must be 1-80 safe characters"])
        }
        let store = store()
        let ok = await store.finish()
        XCTAssertFalse(ok)
        XCTAssertEqual(store.step, .name)
        XCTAssertEqual(store.nameMessage, "Your name must be 1 to 80 ordinary characters.")
    }

    func testSkipVisionFinishesWithoutSubmittingAKey() async throws {
        OnboardingFixtures.stubKeys(allowOwn: false)
        OnboardingFixtures.stubFinish()
        let store = store()
        await store.text.load()
        await store.continueFlow()
        XCTAssertEqual(store.step, .vision)
        XCTAssertTrue(store.canGoBack)

        await store.skipVision()

        XCTAssertEqual(store.step, .ready)
        XCTAssertEqual(store.primaryLabel, "Start")
        XCTAssertFalse(store.canGoBack)
        XCTAssertTrue(StubURLProtocol.recorded("PUT", "/v1/ai-keys").isEmpty)
        XCTAssertEqual(StubURLProtocol.recorded("PUT", "/v1/me/settings").count, 1)

        let finished = CallCounter()
        store.onFinished = { _ = finished.next() }
        await store.continueFlow()
        XCTAssertEqual(finished.next(), 2, "Start hands control back to the owner")
    }

    // MARK: Name

    func testNameStepValidatesBeforeMovingOn() async throws {
        let store = store(name: "")
        XCTAssertEqual(store.step, .name)
        XCTAssertFalse(store.canContinue)
        XCTAssertFalse(store.canGoBack)
        store.name = "Ada\u{0007}"
        XCTAssertTrue(store.canContinue)
        await store.continueFlow()
        XCTAssertEqual(store.step, .name)
        XCTAssertEqual(store.nameMessage, OnboardingStore.Copy.nameInvalid)
        store.name = "  Grace   Hopper "
        await store.continueFlow()
        XCTAssertEqual(store.step, .provider)
        XCTAssertEqual(store.name, "Grace Hopper")
        XCTAssertNil(store.nameMessage)
        XCTAssertTrue(store.canGoBack)
        store.back()
        XCTAssertEqual(store.step, .name)
    }

    func testNameRuleMatchesTheServer() {
        XCTAssertEqual(OnboardingStore.normalizedName("  Ada   Lovelace "), "Ada Lovelace")
        XCTAssertNil(OnboardingStore.normalizedName(""))
        XCTAssertNil(OnboardingStore.normalizedName("   \n "))
        XCTAssertEqual(OnboardingStore.normalizedName(String(repeating: "a", count: 80))?.count, 80)
        XCTAssertNil(OnboardingStore.normalizedName(String(repeating: "a", count: 81)))
        XCTAssertNil(OnboardingStore.normalizedName("Ada\u{0007}"), "control characters are refused")
        XCTAssertNil(OnboardingStore.normalizedName("Ada\u{200B}"), "format characters are refused")
        XCTAssertEqual(OnboardingStore.normalizedName("Zoë Ñandú"), "Zoë Ñandú")
    }

    // MARK: Client mapping

    func testClientTurnsServerSentencesIntoOutcomesAndThrowsTheRest() async throws {
        let submission = AIKeySubmission(level: "user", provider: "openai", model: "openai/gpt-4.1", modality: .text, baseURL: nil, apiKey: "k")
        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in
            StubURLProtocol.json(503, ["status": "unavailable", "reason": "The saved key could not be read. Submit the provider again."])
        }
        let unavailable = try await client.setAIKey(submission)
        XCTAssertEqual(unavailable, .refused(reason: "The saved key could not be read. Submit the provider again."))

        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(400, ["status": "error", "reason": "an API key is required for this provider"]) }
        let invalid = try await client.setAIKey(submission)
        XCTAssertEqual(invalid, .refused(reason: "an API key is required for this provider"))

        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in
            StubURLProtocol.json(202, ["status": "pending_human", "proposal": OnboardingFixtures.proposal])
        }
        let pending = try await client.setAIKey(submission)
        XCTAssertEqual(pending, .pendingHuman(AIKeyProposal(id: "akp_1", provider: "openai", model: "openai/gpt-4.1", modality: "text", status: "pending")))

        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(403, ["status": "denied", "reason": "org AI key requires org administration"]) }
        do {
            _ = try await client.setAIKey(submission)
            XCTFail("a 403 is still thrown")
        } catch let error as BoltrigError {
            XCTAssertEqual(error.kind, .forbidden)
        }

        StubURLProtocol.on("PUT", "/v1/ai-keys") { _ in StubURLProtocol.json(401, ["detail": "invalid or expired access token"]) }
        do {
            _ = try await client.setAIKey(submission)
            XCTFail("a dead token is still thrown")
        } catch let error as BoltrigError {
            XCTAssertEqual(error.kind, .unauthenticated)
        }

        XCTAssertEqual(BoltrigClient.mapError(status: 503, data: #"{"status":"unavailable","reason":"x"}"#.data(using: .utf8)!).kind,
                       .server(status: 503, reason: "x"))
        XCTAssertEqual(BoltrigClient.mapError(status: 503, data: Data()).kind, .server(status: 503))
        XCTAssertEqual(AIKeyOutcome.decode(#"{"status":"pending_human"}"#.data(using: .utf8)!), .refused(reason: ""))
        XCTAssertEqual(AIKeyOutcome.decode(Data()), .refused(reason: ""))
    }

    func testProfilePatchSendsTheName() async throws {
        StubURLProtocol.on("PATCH", "/v1/me/profile") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        try await client.updateProfile(displayName: "Ada")
        let request = try XCTUnwrap(StubURLProtocol.recorded("PATCH", "/v1/me/profile").first)
        XCTAssertEqual(try OnboardingFixtures.sentJSON(request)["display_name"] as? String, "Ada")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer boltrig_pat_x")
    }

    // MARK: Catalogue

    func testBundledCatalogueLoadsOffMainWithSelfHostedOllamaBeforeOllamaCloud() async throws {
        let start = ContinuousClock.now
        let catalogue = try await ProviderCatalogue.load(bundle: Bundle.main)
        let elapsed = ContinuousClock.now - start

        XCTAssertLessThan(elapsed, .milliseconds(150), "decode took \(elapsed)")
        XCTAssertEqual(catalogue.revision, ProviderCatalogue.pinnedRevision,
                       "run ios/scripts/sync-provider-catalogue.sh and bump pinnedRevision together")
        XCTAssertEqual(catalogue.license, "MIT")
        XCTAssertEqual(catalogue.source, "https://models.dev/api.json")
        let ids = catalogue.providers.map(\.id)
        let ollama = try XCTUnwrap(ids.firstIndex(of: "ollama"))
        XCTAssertEqual(ids[ollama + 1], "ollama-cloud")
        XCTAssertEqual(ids.filter { $0 == "ollama" }.count, 1)
        XCTAssertTrue(catalogue.provider("ollama")?.requiresBaseURL == true)
        XCTAssertTrue(catalogue.provider("ollama")?.models.isEmpty == true)
        XCTAssertTrue(catalogue.keyOptional("ollama"))
        XCTAssertFalse(catalogue.keyOptional("openai"))
        XCTAssertTrue(catalogue.needsBaseURL("ollama"))
        XCTAssertTrue(catalogue.needsBaseURL("custom"))
        XCTAssertFalse(catalogue.needsBaseURL("openai"))
        XCTAssertFalse(catalogue.needsBaseURL("deepseek"), "a published address is submitted silently")
        XCTAssertEqual(catalogue.publishedBaseURL("deepseek"), "https://api.deepseek.com")
        XCTAssertTrue(catalogue.needsBaseURL("togetherai"), "non-native and no published address")
        XCTAssertFalse((catalogue.provider("openai")?.models ?? []).isEmpty)
        XCTAssertGreaterThan(catalogue.providers.count, 150)
        let shared = try await ProviderCatalogue.shared()
        XCTAssertEqual(shared.revision, catalogue.revision)
    }

    func testCatalogueRules() {
        XCTAssertEqual(ProviderCatalogue.exactModelID(provider: "openai", model: "gpt-4.1"), "openai/gpt-4.1")
        XCTAssertEqual(ProviderCatalogue.exactModelID(provider: "openai", model: "openai/gpt-4.1"), "openai/gpt-4.1")
        XCTAssertEqual(ProviderCatalogue.exactModelID(provider: "custom", model: "my-model"), "my-model")
        XCTAssertEqual(ProviderCatalogue.exactModelID(provider: " ollama ", model: " x "), "ollama/x")
        XCTAssertEqual(ProviderCatalogue.bifrostProviderID("google"), "gemini")
        XCTAssertEqual(ProviderCatalogue.bifrostProviderID(" X-AI "), "xai")
        XCTAssertTrue(ProviderCatalogue.isBifrostSupported("amazon-bedrock"))
        XCTAssertFalse(ProviderCatalogue.isBifrostSupported("deepseek"))
        let small = OnboardingFixtures.smallCatalogue
        XCTAssertEqual(small.providers.map(\.id), ["openai", "deepseek", "togetherai", "ollama", "ollama-cloud", "custom"])
        XCTAssertEqual(small.provider("openai")?.models.first?.label, "GPT-4.1")
        XCTAssertEqual(small.provider("openai")?.models.last?.label, "o3-mini")
        XCTAssertTrue(small.provider("openai")?.models.first?.vision == true)
        XCTAssertFalse(small.needsBaseURL("nowhere"))
        XCTAssertEqual(ProviderCatalogue.minimal.providers.map(\.id), ["ollama", "custom"])
    }

    // MARK: Root gate

    func testRootDestinationResolve() {
        XCTAssertEqual(RootDestination.resolve(OnboardingFixtures.account(onboarded: false)), .onboarding)
        XCTAssertEqual(RootDestination.resolve(OnboardingFixtures.account(onboarded: true)), .workspace)
        XCTAssertEqual(OnboardingStore.startStep(for: OnboardingFixtures.account(name: "")), .name)
        XCTAssertEqual(OnboardingStore.startStep(for: OnboardingFixtures.account(name: "Ada")), .provider)
    }
}
