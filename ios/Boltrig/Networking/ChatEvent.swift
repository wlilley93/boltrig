import Foundation

/// The events a chat turn streams back, reduced to what the phone renders today.
/// Every type the server can send is named here so nothing is silently dropped;
/// the ones the app does not render yet arrive as `.other`.
enum ChatEvent: Equatable {
    /// The 202 answer: the message joined the queue behind a run already in flight.
    case queued(conversationID: String?)
    case messageStart(runID: String, conversationID: String)
    case textDelta(String, degraded: Bool)
    case reasoningDelta(String)
    case toolCall(verb: String?, status: String?)
    case toolResult(verb: String?, status: String?)
    case needsYou(requestID: String, question: String?)
    case question(id: String, prompt: String)
    case heartbeat
    case messageEnd(runID: String)
    case cancelled(runID: String)
    case other(type: String)

    /// Builds an event from one decoded `data:` frame. Unknown or malformed frames become
    /// `.other` rather than failing the turn: the server's vocabulary may grow before the app does.
    static func from(json object: [String: Any]) -> ChatEvent {
        let type = object["type"] as? String ?? "unknown"
        switch type {
        case "message_start":
            return .messageStart(runID: object["run_id"] as? String ?? "",
                                 conversationID: object["conversation_id"] as? String ?? "")
        case "text_delta":
            return .textDelta(object["delta"] as? String ?? "", degraded: object["degraded"] as? Bool ?? false)
        case "reasoning_delta":
            return .reasoningDelta(object["delta"] as? String ?? "")
        case "tool_call":
            return .toolCall(verb: object["verb"] as? String ?? object["tool"] as? String,
                             status: object["status"] as? String)
        case "tool_result":
            return .toolResult(verb: object["verb"] as? String, status: object["status"] as? String)
        case "hitl":
            return .needsYou(requestID: object["hitl_request_id"] as? String ?? "",
                             question: object["question"] as? String)
        case "question":
            return .question(id: object["question_id"] as? String ?? "", prompt: object["prompt"] as? String ?? "")
        case "heartbeat":
            return .heartbeat
        case "message_end":
            return .messageEnd(runID: object["run_id"] as? String ?? "")
        case "cancelled":
            return .cancelled(runID: object["run_id"] as? String ?? "")
        default:
            return .other(type: type)
        }
    }
}

/// Splits a server-sent event stream into decoded frames. Frames are `data:` lines ended
/// by a blank line; several `data:` lines in one frame are joined with a newline.
struct SSEFrameParser {
    private var pending: [String] = []

    /// Feed one line (without its terminator). Returns a decoded frame when one completes.
    mutating func consume(line: String) -> [String: Any]? {
        if line.isEmpty {
            return flush()
        }
        if line.hasPrefix("data:") {
            var payload = line.dropFirst(5)
            if payload.hasPrefix(" ") { payload = payload.dropFirst() }
            pending.append(String(payload))
        }
        return nil
    }

    /// Call at end of stream: a final frame without a trailing blank line still counts.
    mutating func flush() -> [String: Any]? {
        guard !pending.isEmpty else { return nil }
        let joined = pending.joined(separator: "\n")
        pending.removeAll()
        guard let data = joined.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return ["type": "malformed_event"]
        }
        return object
    }
}
