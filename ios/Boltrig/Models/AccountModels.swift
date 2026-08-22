import Foundation

/// How Boltrig decides when to ask before a delegated tool acts. The phone reads this;
/// changing it needs a person signed in on the web (the server refuses the phone's key).
struct ApprovalPostureReading: Equatable {
    enum Posture: String, CaseIterable {
        case alwaysAsk = "always_ask"
        case riskBased = "risk_based"
        case fullAccess = "full_access"

        var title: String {
            switch self {
            case .alwaysAsk: return "Ask for approval"
            case .riskBased: return "Approve for me"
            case .fullAccess: return "Full access"
            }
        }

        /// The web's own descriptions (ApprovalPostureControl), word for word.
        var detail: String {
            switch self {
            case .alwaysAsk: return "Ask before every delegated agent tool uses an external adapter."
            case .riskBased: return "Ask only for high-consequence actions and workspace-required approvals."
            case .fullAccess: return "Use already-granted external tools without asking; hard limits still apply."
            }
        }
    }

    let posture: Posture
    let source: String

    static func decode(_ data: Data) throws -> ApprovalPostureReading {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let raw = root["posture"] as? String, let posture = Posture(rawValue: raw) else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        return ApprovalPostureReading(posture: posture, source: root["source"] as? String ?? "")
    }
}

/// One signed-in session on the web or the desktop, from `GET /v1/me/sessions`.
struct UserSession: Identifiable, Equatable, Decodable {
    let id: String
    let client: String?
    let revoked: Bool
    let createdAt: String?
    let lastSeenAt: String?

    enum CodingKeys: String, CodingKey {
        case id, client, revoked
        case createdAt = "created_at"
        case lastSeenAt = "last_seen_at"
    }

    var clientLabel: String {
        let value = (client ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "Unknown client" : value
    }

    var lastSeenLabel: String {
        guard let lastSeenAt, !lastSeenAt.relativeAge.isEmpty else { return "Not seen yet" }
        let age = lastSeenAt.relativeAge
        return age == "now" ? "Seen just now" : "Seen \(age) ago"
    }

    static func decodeList(_ data: Data) throws -> [UserSession] {
        struct Envelope: Decodable { let sessions: [UserSession] }
        return try AccountDecoding.decode(Envelope.self, from: data).sessions
    }
}

/// One key on this account as the server lists it: never the secret.
struct AccessTokenView: Identifiable, Equatable, Decodable {
    let id: String
    let name: String
    let scope: [String]
    let createdAt: String?
    let lastUsedAt: String?
    let expiresAt: String?
    let revoked: Bool
    /// Set by the store when this is the key the phone itself signs in with.
    var isThisPhone = false

    enum CodingKeys: String, CodingKey {
        case id, name, scope, revoked
        case createdAt = "created_at"
        case lastUsedAt = "last_used_at"
        case expiresAt = "expires_at"
    }

    func expiryLabel(now: Date = Date()) -> String {
        guard let expiresAt, let date = LinkedDevice.date(expiresAt) else { return "Does not expire" }
        let days = Int((date.timeIntervalSince(now) / 86_400).rounded(.up))
        if days <= 0 { return "Expired" }
        if days == 1 { return "Expires tomorrow" }
        return "Expires in \(days) days"
    }

    static func decodeList(_ data: Data) throws -> [AccessTokenView] {
        struct Envelope: Decodable { let tokens: [AccessTokenView] }
        return try AccountDecoding.decode(Envelope.self, from: data).tokens
    }
}

/// One spending ceiling from `GET /v1/budgets`, in the kernel's micro-dollars.
struct BudgetView: Identifiable, Equatable, Decodable {
    let id: String
    let scopeType: String
    let window: String
    let hardStop: Bool
    let tokenLimit: Int?
    let spentTokens: Int?
    let costLimitMicros: Int?
    let spentMicros: Int?
    let windowEndsAt: String?

    enum CodingKeys: String, CodingKey {
        case id, window
        case scopeType = "scope_type"
        case hardStop = "hard_stop"
        case tokenLimit = "token_limit"
        case spentTokens = "spent_tokens"
        case costLimitMicros = "cost_limit_micros"
        case spentMicros = "spent_micros"
        case windowEndsAt = "window_ends_at"
    }

    /// "This month", "Today", "Each run", with the scope when it is narrower than the whole.
    var title: String {
        let period: String
        switch window {
        case "run": period = "Each run"
        case "daily": period = "Today"
        case "monthly": period = "This month"
        default: period = window.capitalized
        }
        return scopeType == "tenant" || scopeType.isEmpty ? period : "\(period), \(scopeType)"
    }

    /// "{spent} of {limit}" in money when a money ceiling exists, otherwise in usage.
    var spentLabel: String {
        if let costLimitMicros {
            return "\(CostSummary.money(micros: spentMicros ?? 0)) of \(CostSummary.money(micros: costLimitMicros))"
        }
        if let tokenLimit {
            return "\(CostSummary.count(spentTokens ?? 0)) of \(CostSummary.count(tokenLimit))"
        }
        return "\(CostSummary.money(micros: spentMicros ?? 0)) spent, no ceiling"
    }

    var note: String {
        if costLimitMicros == nil && tokenLimit != nil { return "This ceiling counts usage, not money." }
        return hardStop ? "Work stops when this ceiling is reached." : "Recorded and reported, but does not stop work."
    }

    static func decodeList(_ data: Data) throws -> [BudgetView] {
        struct Envelope: Decodable { let budgets: [BudgetView] }
        return try AccountDecoding.decode(Envelope.self, from: data).budgets
    }
}

/// What has been spent, from `GET /v1/cost`.
struct CostSummary: Equatable, Decodable {
    let totalMicros: Int
    let byActor: [String: Int]

    enum CodingKeys: String, CodingKey {
        case totalMicros = "total_cost_micros"
        case byActor = "by_actor"
    }

    var totalLabel: String { Self.money(micros: totalMicros) }

    /// Micro-dollars to "$12.40". Pinned to one shape so the screen agrees with the web.
    static func money(micros: Int) -> String {
        guard micros > 0 else { return "$0.00" }
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "en_US")
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.currencySymbol = "$"
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: Double(micros) / 1_000_000)) ?? "$0.00"
    }

    static func count(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "en_US")
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    static func decode(_ data: Data) throws -> CostSummary {
        try AccountDecoding.decode(CostSummary.self, from: data)
    }
}

/// `GET /readyz`, reduced to plain words. The server answers 503 when something required is
/// down; the body is the same shape either way and is what the screen shows.
struct ReadinessReport: Equatable {
    struct Check: Identifiable, Equatable {
        let id: String
        let label: String
        let status: String
        let required: Bool
        let reason: String?

        var isWorking: Bool { status == "ok" }

        var statusLabel: String {
            switch status {
            case "ok": return "Working"
            case "failed": return "Not working"
            case "disabled": return "Not in use"
            case "unchecked", "not_evaluated", "not_required": return "Not checked"
            default: return status.replacingOccurrences(of: "_", with: " ").capitalized
            }
        }
    }

    let ready: Bool
    let checks: [Check]

    static let labels: [String: String] = [
        "postgres": "Records",
        "redis": "Live updates",
        "migration": "Records are up to date",
        "control_plane": "Control",
        "stack_tools": "Tools",
        "hatchet": "Background work",
        "model_gateway": "Your AI",
        "codex_runtime": "Code runtime",
        "password_reset_delivery": "Reset emails",
    ]

    static let order = ["postgres", "migration", "redis", "control_plane", "stack_tools", "hatchet",
                        "model_gateway", "codex_runtime", "password_reset_delivery"]

    static func label(for key: String) -> String {
        labels[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
    }

    static func decode(_ data: Data) throws -> ReadinessReport {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let status = root["status"] as? String else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        let raw = root["checks"] as? [String: Any] ?? [:]
        let keys = order.filter { raw[$0] != nil } + raw.keys.filter { !order.contains($0) }.sorted()
        let checks = keys.compactMap { key -> Check? in
            guard let item = raw[key] as? [String: Any] else { return nil }
            return Check(id: key, label: label(for: key), status: item["status"] as? String ?? "unknown",
                         required: Account.flag(item["required"]), reason: item["reason"] as? String)
        }
        return ReadinessReport(ready: status == "ready", checks: checks)
    }
}

enum AccountDecoding {
    static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
    }
}
