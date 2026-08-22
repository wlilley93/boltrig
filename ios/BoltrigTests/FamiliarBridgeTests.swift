import XCTest
@testable import Boltrig

final class FamiliarBridgeTests: XCTestCase {
    func testStateEncodesSortedKeysAndClamps() throws {
        var state = FamiliarIslandState()
        state.mode = .speaking
        state.level = 1.7
        state.onset = -0.2
        state.dprCap = 9
        state.bands = [0, 0.5, 2, -1, 0.25, 0.75, 1, Double.nan]
        state.phenotype = ["valence": 1.5, "arousal": 0.25]
        let json = try state.json()
        XCTAssertTrue(json.hasPrefix("{\"appearance\":\"dark\",\"bands\":[0,0.5,1,0,0.25,0.75,1,0],\"dprCap\":2,"), json)
        XCTAssertTrue(json.contains("\"level\":1,"))
        XCTAssertTrue(json.contains("\"mode\":\"speaking\""))
        XCTAssertTrue(json.contains("\"onset\":0,"))
        XCTAssertTrue(json.contains("\"phenotype\":{\"arousal\":0.25,\"valence\":1}"))
        XCTAssertTrue(json.contains("\"v\":1"))
        var sevenBands = state
        sevenBands.bands = [1, 1, 1]
        XCTAssertFalse(try sevenBands.json().contains("\"bands\":["), "a band array that is not eight wide is dropped")
        XCTAssertEqual(try state.json(), try state.json(), "equal states encode identically")
    }

    func testReportsDecode() {
        XCTAssertEqual(FamiliarIslandReport(message: ["v": 1, "type": "ready", "renderer": "webgl2", "fragSha256": "abc"]),
                       .ready(renderer: "webgl2", fragSha256: "abc"))
        XCTAssertEqual(FamiliarIslandReport(message: ["type": "fallback", "reason": "no webgl2"]), .fallback(reason: "no webgl2"))
        XCTAssertEqual(FamiliarIslandReport(message: ["type": "frame", "fps": 29.5, "frameMs": 3]), .frame(fps: 29.5, frameMs: 3))
        XCTAssertEqual(FamiliarIslandReport(message: ["type": "error", "message": "boom"]), .error(message: "boom"))
        XCTAssertEqual(FamiliarIslandReport(message: ["type": "later"]), .unknown(type: "later"))
        XCTAssertNil(FamiliarIslandReport(message: "not a dictionary"))
    }

    func testModePrecedenceMatchesTheWeb() {
        XCTAssertEqual(FamiliarModeResolver.mode(failed: true, speaking: true, listening: true, streaming: true, loading: true), .error)
        XCTAssertEqual(FamiliarModeResolver.mode(failed: false, speaking: true, listening: true, streaming: true, loading: true), .speaking)
        XCTAssertEqual(FamiliarModeResolver.mode(failed: false, speaking: false, listening: true, streaming: true, loading: true), .listening)
        XCTAssertEqual(FamiliarModeResolver.mode(failed: false, speaking: false, listening: false, streaming: true, loading: true), .working)
        XCTAssertEqual(FamiliarModeResolver.mode(failed: false, speaking: false, listening: false, streaming: false, loading: true), .thinking)
        XCTAssertEqual(FamiliarModeResolver.mode(failed: false, speaking: false, listening: false, streaming: false, loading: false), .standby)
    }

    func testGenotypeIdentity() {
        XCTAssertEqual(FamiliarVisualIdentity(genotype: nil), .neutral)
        let unbound = FamiliarGenotype(source: "something-else", seed: 9, body: "kepler", palette: ["#111111", "#222222", "#333333"], markings: ["arc"], accessories: ["antenna"])
        XCTAssertEqual(FamiliarVisualIdentity(genotype: unbound), .neutral, "only the capability-name source binds")
        let bound = FamiliarGenotype(source: FamiliarVisualIdentity.boundSource, seed: 25, body: "kepler",
                                     palette: ["#FFEEDD", "#3B82F6", "#172554"], markings: ["arc", "mystery", "halo"], accessories: ["orbit-ring"])
        let identity = FamiliarVisualIdentity(genotype: bound)
        XCTAssertTrue(identity.bound)
        XCTAssertEqual(identity.body, .kepler)
        XCTAssertEqual(identity.palette, ["#FFEEDD", "#3B82F6", "#172554"])
        XCTAssertEqual(identity.markings, [.arc, .halo], "unknown markings are dropped, not guessed")
        XCTAssertEqual(identity.accessories, [.orbitRing])
        XCTAssertEqual(identity.bodyRotationDegrees, Double((25 % 17) - 8) * 0.55, accuracy: 0.0001)
        let badPalette = FamiliarGenotype(source: FamiliarVisualIdentity.boundSource, seed: 1, body: "voyager", palette: ["red", "green", "blue"], markings: nil, accessories: nil)
        XCTAssertEqual(FamiliarVisualIdentity(genotype: badPalette).palette, FamiliarVisualIdentity.neutralPalette)
        let unknownBody = FamiliarGenotype(source: FamiliarVisualIdentity.boundSource, seed: 1, body: "comet", palette: nil, markings: nil, accessories: nil)
        XCTAssertEqual(FamiliarVisualIdentity(genotype: unknownBody).body, .neutral)
    }

    func testRadialPolygonStartsAtTheTop() {
        let path = FamiliarBadgeView.radialPolygon(points: 5, outer: 8.1, inner: 3.45)
        XCTAssertEqual(path.boundingRect.minY, 12 - 8.1, accuracy: 0.01)
    }
}
