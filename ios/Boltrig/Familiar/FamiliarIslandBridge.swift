import Foundation

/// The v1 contract between the phone and the Familiar island (the web view that runs her
/// shader). Closed enums and bounded numbers only; nothing here carries text, identifiers or
/// secrets. The island keeps any field the phone does not send.
struct FamiliarIslandState: Codable, Equatable {
    enum Mode: String, Codable, CaseIterable {
        case standby, listening, thinking, working, speaking, error
    }

    enum Presentation: String, Codable {
        case hero, conversation, minimised
    }

    enum Appearance: String, Codable {
        case dark, light
    }

    var v: Int = 1
    var mode: Mode = .standby
    var level: Double = 0
    var bands: [Double]? = nil
    var onset: Double = 0
    var presentation: Presentation = .conversation
    var reducedMotion: Bool = false
    var appearance: Appearance = .dark
    var dprCap: Double = 2
    var phenotype: [String: Double]? = nil
    var genotype: FamiliarGenotype? = nil

    /// Clamps what must be clamped so the island never sees a value outside its contract.
    func clamped() -> FamiliarIslandState {
        var copy = self
        copy.level = Self.unit(level)
        copy.onset = Self.unit(onset)
        copy.dprCap = min(2, max(1, dprCap.isFinite ? dprCap : 2))
        if let bands, bands.count == 8 {
            copy.bands = bands.map(Self.unit)
        } else {
            copy.bands = nil
        }
        if let phenotype {
            copy.phenotype = phenotype.mapValues(Self.unit)
        }
        return copy
    }

    /// JSON with stable key order, so two equal states encode identically.
    func json() throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return String(decoding: try encoder.encode(clamped()), as: UTF8.self)
    }

    static func unit(_ value: Double) -> Double {
        guard value.isFinite else { return 0 }
        return min(1, max(0, value))
    }
}

/// What the island tells the phone.
enum FamiliarIslandReport: Equatable {
    case ready(renderer: String, fragSha256: String?)
    case fallback(reason: String)
    case frame(fps: Double, frameMs: Double)
    case error(message: String)
    case unknown(type: String)

    init?(message: Any) {
        guard let object = message as? [String: Any], let type = object["type"] as? String else { return nil }
        switch type {
        case "ready":
            self = .ready(renderer: object["renderer"] as? String ?? "unknown", fragSha256: object["fragSha256"] as? String)
        case "fallback":
            self = .fallback(reason: object["reason"] as? String ?? "")
        case "frame":
            self = .frame(fps: Self.number(object["fps"]), frameMs: Self.number(object["frameMs"]))
        case "error":
            self = .error(message: object["message"] as? String ?? "")
        default:
            self = .unknown(type: type)
        }
    }

    private static func number(_ value: Any?) -> Double {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        return 0
    }
}

/// The mode the presence shows, derived exactly as the web's `familiarStateFromTurn` does:
/// error outranks speaking, speaking outranks listening, listening outranks a background
/// turn, working is a turn with live text, thinking is a turn with none yet.
enum FamiliarModeResolver {
    static func mode(failed: Bool, speaking: Bool, listening: Bool, streaming: Bool, loading: Bool) -> FamiliarIslandState.Mode {
        if failed { return .error }
        if speaking { return .speaking }
        if listening { return .listening }
        if streaming { return .working }
        if loading { return .thinking }
        return .standby
    }
}
