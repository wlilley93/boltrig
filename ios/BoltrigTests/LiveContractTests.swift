import XCTest
@testable import Boltrig

/// The one suite that talks to a real Boltrig instance. It runs only when a credential is in
/// the environment, so the ordinary suite never touches the network:
///
///   xcodebuild ... test -only-testing:BoltrigTests/LiveContractTests \
///     TEST_RUNNER_BOLTRIG_LIVE_EMAIL=... TEST_RUNNER_BOLTRIG_LIVE_PASSWORD=... \
///     [TEST_RUNNER_BOLTRIG_LIVE_INSTANCE=https://dev.boltrig.ai]
///
/// Use a throwaway account: signing in switches its companion to Familiar (by design) and
/// sends one short chat turn. The phone's token is revoked at the end by signing out.
@MainActor
final class LiveContractTests: XCTestCase {
    private var email = ""
    private var password = ""
    private var instance = BoltrigEnvironment.hostedInstanceURL

    override func setUpWithError() throws {
        let env = ProcessInfo.processInfo.environment
        guard let e = env["BOLTRIG_LIVE_EMAIL"], let p = env["BOLTRIG_LIVE_PASSWORD"], !e.isEmpty, !p.isEmpty else {
            throw XCTSkip("no BOLTRIG_LIVE_EMAIL / BOLTRIG_LIVE_PASSWORD in the environment")
        }
        email = e
        password = p
        if let raw = env["BOLTRIG_LIVE_INSTANCE"], let url = URL(string: raw) { instance = url }
    }

    func testSignInAdoptionReadsAndOneChatTurnAgainstTheInstance() async throws {
        let defaults = UserDefaults(suiteName: "live-contract-\(UUID().uuidString)")!
        let session = SessionStore(vault: InMemorySessionVault(), configuration: .ephemeral, defaults: defaults)
        await session.useInstance(instance)
        await session.signIn(email: email, password: password)
        guard case let .signedIn(account) = session.state else {
            return XCTFail("sign-in did not reach signedIn: \(session.state), message \(session.errorMessage ?? "none")")
        }
        XCTAssertEqual(account.companionPresence, .familiar, "the phone switches the account to Familiar on first sign-in")
        let client = try XCTUnwrap(session.apiClient)

        // Reads the app makes on its first screens.
        let limits = try await client.chatConfig()
        XCTAssertGreaterThan(limits.maxCount, 0)
        let capabilities = try await client.capabilities()
        XCTAssertNotNil(capabilities)
        _ = try await client.conversations()
        _ = try await client.approvals()
        _ = try await client.devices()
        _ = try await client.tokens()
        let readiness = try await client.readiness()
        XCTAssertFalse(readiness.checks.isEmpty)

        // One short turn, bounded: the reply text or a visible failure within the limit.
        let chat = ChatSession(client: client)
        chat.startNew()
        let turn = Task { await chat.sendMessage("Reply with the single word: ready") }
        let deadline = Date().addingTimeInterval(90)
        while chat.isSending && Date() < deadline {
            try await Task.sleep(nanoseconds: 500_000_000)
        }
        turn.cancel()
        XCTAssertFalse(chat.isSending, "the turn did not settle within 90 s")
        XCTAssertFalse(chat.messages.isEmpty)
        if chat.turnFailed {
            // A provider that is not connected on this account is a truthful outcome, not a test failure:
            // the copy must be plain and the session intact.
            XCTAssertFalse(chat.messages.last?.content.isEmpty ?? true)
        }

        await session.signOut()
        guard case .signedOut = session.state else { return XCTFail("sign-out left state \(session.state)") }
    }
}
