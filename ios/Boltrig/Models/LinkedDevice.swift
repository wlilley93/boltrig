import Foundation

/// A computer running Boltrig Desktop, signed in with this account. The server marks it
/// online on every request it makes and refreshes `last_seen_at`; it never marks it offline,
/// so liveness is read from the last-seen time against the desktop's three-second poll.
struct LinkedDevice: Identifiable, Equatable {
    struct Root: Equatable {
        let id: String
        let label: String
        let scope: String
        let commandEnabled: Bool
    }

    static let liveWindow: TimeInterval = 20

    let id: String
    let label: String
    let presence: String
    let lastSeenAt: Date?
    let revokedAt: Date?
    let roots: [Root]

    func isOn(now: Date = Date()) -> Bool {
        guard revokedAt == nil, presence == "online", let lastSeenAt else { return false }
        return now.timeIntervalSince(lastSeenAt) <= Self.liveWindow
    }

    func statusLabel(now: Date = Date()) -> String {
        if revokedAt != nil { return "Disconnected" }
        if isOn(now: now) { return "On" }
        guard let lastSeenAt else { return "Never seen" }
        let seconds = max(0, Int(now.timeIntervalSince(lastSeenAt)))
        if seconds < 60 { return "Seen just now" }
        if seconds < 3600 { return "Seen \(seconds / 60)m ago" }
        if seconds < 86_400 { return "Seen \(seconds / 3600)h ago" }
        return "Seen \(seconds / 86_400)d ago"
    }

    static func decodeList(_ data: Data) throws -> [LinkedDevice] {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rows = root["devices"] as? [[String: Any]] else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        return rows.compactMap(decode)
    }

    static func decode(_ object: [String: Any]) -> LinkedDevice? {
        guard let id = object["id"] as? String else { return nil }
        let roots = (object["roots"] as? [[String: Any]] ?? []).compactMap { root -> Root? in
            guard let rootID = root["id"] as? String else { return nil }
            return Root(id: rootID, label: root["label"] as? String ?? "", scope: root["scope"] as? String ?? "read",
                        commandEnabled: root["command_enabled"] as? Bool ?? false)
        }
        return LinkedDevice(
            id: id,
            label: (object["label"] as? String ?? "").isEmpty ? "This computer" : (object["label"] as? String ?? ""),
            presence: object["presence"] as? String ?? "offline",
            lastSeenAt: (object["last_seen_at"] as? String).flatMap(Self.date),
            revokedAt: (object["revoked_at"] as? String).flatMap(Self.date),
            roots: roots
        )
    }

    static func date(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}
