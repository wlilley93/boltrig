import Foundation

/// What the server can do right now, reduced to what the phone reads.
struct CapabilitiesSnapshot: Equatable {
    struct Verb: Equatable {
        let id: String
        let bindingTargetType: String?
        let bindingTargetRef: String?
    }

    let verbs: [Verb]

    /// The adapter behind a verb, if one is bound.
    func provider(for verbID: String) -> String? {
        verbs.first { $0.id == verbID && $0.bindingTargetType == "adapter" }?.bindingTargetRef
    }

    static func decode(_ data: Data) throws -> CapabilitiesSnapshot {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        let rows = (root["verbs"] as? [[String: Any]]) ?? (root["capabilities"] as? [[String: Any]]) ?? []
        let verbs = rows.compactMap { row -> Verb? in
            guard let id = (row["id"] as? String) ?? (row["verb"] as? String) else { return nil }
            let binding = row["binding"] as? [String: Any]
            return Verb(id: id, bindingTargetType: binding?["target_type"] as? String, bindingTargetRef: binding?["target_ref"] as? String)
        }
        return CapabilitiesSnapshot(verbs: verbs)
    }
}

/// The answer to an invoke: done with an output, waiting for a person, or refused.
enum InvokeOutcome: Equatable {
    case ok(output: [String: AnyHashable])
    case pendingHuman
    case refused(reason: String)

    static func decode(_ data: Data, status: Int) -> InvokeOutcome {
        let object = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        let state = object["status"] as? String ?? ""
        if status == 202 || state == "pending_human" { return .pendingHuman }
        if state == "ok" {
            let output = (object["output"] as? [String: Any]) ?? object
            return .ok(output: output.compactMapValues { $0 as? AnyHashable })
        }
        return .refused(reason: (object["reason"] as? String) ?? (object["detail"] as? String) ?? state)
    }
}

/// Familiar's inner life as the server projects it; `nil` when nothing fresh is known.
struct PhenotypeReading: Equatable {
    let fresh: Bool
    let values: [String: Double]?

    static func decode(_ data: Data) -> PhenotypeReading {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return PhenotypeReading(fresh: false, values: nil)
        }
        let fresh = root["fresh"] as? Bool ?? false
        let raw = root["phenotype"] as? [String: Any]
        let values = raw?.compactMapValues { value -> Double? in
            if let number = value as? Double { return number }
            if let number = value as? Int { return Double(number) }
            return nil
        }
        return PhenotypeReading(fresh: fresh, values: fresh ? values : nil)
    }
}

extension BoltrigClient {
    func capabilities() async throws -> CapabilitiesSnapshot {
        let (data, _) = try await perform(path: "/v1/capabilities", method: "GET", body: nil)
        return try CapabilitiesSnapshot.decode(data)
    }

    /// Runs one verb through the kernel. 202 and denials are outcomes, not errors.
    func invoke(noun: String, verb: String, params: [String: Any]) async throws -> InvokeOutcome {
        let body = try JSONSerialization.data(withJSONObject: ["noun": noun, "verb": verb, "params": params,
                                                                "idempotency_key": UUID().uuidString])
        do {
            let (data, response) = try await perform(path: "/v1/invoke", method: "POST", body: body)
            return InvokeOutcome.decode(data, status: response.statusCode)
        } catch let error as BoltrigError {
            if case .forbidden = error.kind { return .refused(reason: "forbidden") }
            if case let .rejected(reason) = error.kind { return .refused(reason: reason) }
            throw error
        }
    }

    func familiarPhenotype() async throws -> PhenotypeReading {
        let (data, _) = try await perform(path: "/v1/familiar/phenotype", method: "GET", body: nil)
        return PhenotypeReading.decode(data)
    }
}
