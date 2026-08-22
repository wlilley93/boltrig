import XCTest
@testable import Boltrig

@MainActor
final class LinkedDeviceTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
    }

    private func client() -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_x"),
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    func testDevicesDecodeAndLivenessIsReadFromLastSeen() throws {
        let now = Date()
        let formatter = ISO8601DateFormatter()
        let body: [String: Any] = ["devices": [
            ["id": "d1", "label": "Will's Mac", "public_key_fingerprint": "ab:cd", "presence": "online", "availability_mode": "always",
             "roots": [["id": "r1", "label": "Documents", "scope": "read_write", "command_enabled": true, "git_enabled": false]],
             "last_seen_at": formatter.string(from: now.addingTimeInterval(-4)), "revoked_at": NSNull()],
            ["id": "d2", "label": "Old laptop", "presence": "online", "roots": [],
             "last_seen_at": formatter.string(from: now.addingTimeInterval(-7200)), "revoked_at": NSNull()],
            ["id": "d3", "label": "", "presence": "revoked", "roots": [], "last_seen_at": NSNull(),
             "revoked_at": formatter.string(from: now.addingTimeInterval(-60))],
        ]]
        let devices = try LinkedDevice.decodeList(try JSONSerialization.data(withJSONObject: body))
        XCTAssertEqual(devices.count, 3)
        XCTAssertTrue(devices[0].isOn(now: now))
        XCTAssertEqual(devices[0].statusLabel(now: now), "On")
        XCTAssertEqual(devices[0].roots.first?.commandEnabled, true)
        XCTAssertFalse(devices[1].isOn(now: now), "online is sticky on the server; a stale last-seen means off")
        XCTAssertEqual(devices[1].statusLabel(now: now), "Seen 2h ago")
        XCTAssertEqual(devices[2].label, "This computer")
        XCTAssertEqual(devices[2].statusLabel(now: now), "Disconnected")
    }

    func testRefreshLoadsTheLinkedComputersAndDisconnectRevokes() async throws {
        StubURLProtocol.on("GET", "/v1/conversations") { _ in StubURLProtocol.json(200, ["conversations": []]) }
        StubURLProtocol.on("GET", "/v1/hitl") { _ in StubURLProtocol.json(200, ["requests": []]) }
        StubURLProtocol.on("GET", "/v1/devices") { _ in
            StubURLProtocol.json(200, ["devices": [["id": "d1", "label": "Will's Mac", "presence": "online", "roots": [],
                                                    "last_seen_at": ISO8601DateFormatter().string(from: Date()), "revoked_at": NSNull()]]])
        }
        StubURLProtocol.on("DELETE", "/v1/devices/d1") { _ in StubURLProtocol.json(200, ["status": "ok"]) }
        let store = AppStore(client: client(), account: Account.preview)
        await store.refresh()
        XCTAssertEqual(store.devices.map(\.id), ["d1"])
        XCTAssertNotNil(store.onlineDevice)
        await store.disconnect(store.devices[0])
        XCTAssertTrue(store.devices.isEmpty)
        XCTAssertEqual(StubURLProtocol.recorded("DELETE", "/v1/devices/d1").count, 1)
    }

    func testDevicesFailureLeavesTheRestOfTodayIntact() async {
        StubURLProtocol.on("GET", "/v1/conversations") { _ in StubURLProtocol.json(200, ["conversations": []]) }
        StubURLProtocol.on("GET", "/v1/hitl") { _ in StubURLProtocol.json(200, ["requests": []]) }
        StubURLProtocol.on("GET", "/v1/devices") { _ in StubURLProtocol.json(503, ["status": "error"]) }
        let store = AppStore(client: client(), account: Account.preview)
        await store.refresh()
        XCTAssertNil(store.loadError)
        XCTAssertTrue(store.devices.isEmpty)
    }
}
