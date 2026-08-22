import Foundation

/// The identity a Familiar body can carry. Mirrors `familiarVisualIdentity` in
/// apps/worker/src/components/familiar/FamiliarGenotype.ts: only a genotype whose source is
/// the capability-name contract binds; anything else draws the neutral body so an unknown
/// future value is never guessed into an existing family.
struct FamiliarGenotype: Equatable, Codable {
    var source: String?
    var seed: Double?
    var body: String?
    var palette: [String]?
    var markings: [String]?
    var accessories: [String]?
}

enum FamiliarBody: String, Equatable {
    case cassini, kepler, pioneer, voyager, neutral
}

enum FamiliarMarking: String, Equatable {
    case arc, constellation, halo, orbit
}

enum FamiliarAccessory: String, Equatable {
    case antenna
    case orbitRing = "orbit-ring"
    case signalPin = "signal-pin"
}

struct FamiliarVisualIdentity: Equatable {
    static let boundSource = "agent_capability.name.v1"
    static let neutralPalette = ["#dbeafe", "#3b82f6", "#172554"]

    let bound: Bool
    let seed: UInt32
    let body: FamiliarBody
    /// Light, mid, dark; always three valid `#rrggbb` strings.
    let palette: [String]
    let markings: [FamiliarMarking]
    let accessories: [FamiliarAccessory]

    static let neutral = FamiliarVisualIdentity(bound: false, seed: 0, body: .neutral,
                                                palette: neutralPalette, markings: [], accessories: [])

    init(bound: Bool, seed: UInt32, body: FamiliarBody, palette: [String],
         markings: [FamiliarMarking], accessories: [FamiliarAccessory]) {
        self.bound = bound
        self.seed = seed
        self.body = body
        self.palette = palette
        self.markings = markings
        self.accessories = accessories
    }

    init(genotype: FamiliarGenotype?) {
        guard let genotype, genotype.source == Self.boundSource else {
            self = .neutral
            return
        }
        let body = genotype.body.flatMap { FamiliarBody(rawValue: $0) }.flatMap { $0 == .neutral ? nil : $0 } ?? .neutral
        let palette = Self.validPalette(genotype.palette) ?? Self.neutralPalette
        let seed: UInt32 = {
            guard let value = genotype.seed, value.isFinite, value >= 0 else { return 0 }
            return UInt32(truncatingIfNeeded: Int64(value))
        }()
        self.init(bound: true, seed: seed, body: body, palette: palette,
                  markings: (genotype.markings ?? []).compactMap { FamiliarMarking(rawValue: $0) },
                  accessories: (genotype.accessories ?? []).compactMap { FamiliarAccessory(rawValue: $0) })
    }

    /// The badge's small seeded tilt, in degrees, as the web computes it.
    var bodyRotationDegrees: Double {
        bound ? Double((Int(seed % 17)) - 8) * 0.55 : 0
    }

    static func validPalette(_ values: [String]?) -> [String]? {
        guard let values, values.count >= 3 else { return nil }
        let colours = Array(values.prefix(3))
        let hex = try! NSRegularExpression(pattern: "^#[0-9a-fA-F]{6}$")
        for colour in colours {
            let range = NSRange(colour.startIndex..., in: colour)
            if hex.firstMatch(in: colour, range: range) == nil { return nil }
        }
        return colours
    }
}
