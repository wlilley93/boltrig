import XCTest
@testable import Boltrig

@MainActor
final class PhenotypeTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
    }

    func testPhenotypeDecodesFreshAndRestingShapes() {
        let fresh = PhenotypeReading.decode(#"{"v":1,"fresh":true,"phenotype":{"valence":0.7,"arousal":0.2,"tension":1}}"#.data(using: .utf8)!)
        XCTAssertTrue(fresh.fresh)
        XCTAssertEqual(fresh.values?["valence"], 0.7)
        XCTAssertEqual(fresh.values?["tension"], 1)
        let resting = PhenotypeReading.decode(#"{"v":1,"fresh":false,"phenotype":null}"#.data(using: .utf8)!)
        XCTAssertFalse(resting.fresh)
        XCTAssertNil(resting.values)
        XCTAssertNil(PhenotypeReading.decode(Data()).values)
    }

    func testPollRunsOnlyWhileASurfaceHoldsTheIslandAndTheSceneIsActive() async {
        var served = 0
        StubURLProtocol.on("GET", "/v1/familiar/phenotype") { _ in
            served += 1
            return StubURLProtocol.json(200, ["v": 1, "fresh": true, "phenotype": ["valence": 0.5]])
        }
        let client = BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_x"),
                                   session: URLSession(configuration: Fixtures.stubbedConfiguration))
        let island = FamiliarIslandController()
        island.phenotypeSource = client
        try? await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(served, 0, "nobody is looking yet")
        _ = island.claim("test")
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertEqual(served, 1, "one reading per interval while claimed")
        XCTAssertEqual(island.phenotype?["valence"], 0.5)
        island.setSceneActive(false)
        try? await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertNil(island.phenotype, "backgrounded: the reading is dropped and she wanders")
        island.setSceneActive(true)
        island.release("test")
        try? await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertNil(island.phenotype)
    }
}
