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
    case subagent(childRunID: String, task: String, name: String?)
    case subagentEnd(childRunID: String, status: String)
    case steerQueued
    case steerConsumed
    case needsYou(requestID: String, kind: String?, question: String?, options: [String])
    case question(id: String, prompt: String, choices: [String])
    case heartbeat
    case messageEnd(runID: String)
    case cancelled(runID: String)
    case artifact(name: String, mediaType: String?, size: Int)
    case artifactRejected(count: Int)
    case modelRouting(selected: String?)
    case workflowStep(stepID: String, action: String?, status: String?)
    case workflowRun(status: String?)
    case displayObject
    case eventUnavailable(reason: String?)
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
        case "subagent":
            return .subagent(childRunID: object["child_run_id"] as? String ?? "",
                             task: object["task"] as? String ?? "", name: object["name"] as? String)
        case "subagent_end":
            return .subagentEnd(childRunID: object["child_run_id"] as? String ?? "", status: object["status"] as? String ?? "")
        case "steer_queued":
            return .steerQueued
        case "steer_consumed":
            return .steerConsumed
        case "hitl":
            return .needsYou(requestID: object["hitl_request_id"] as? String ?? "",
                             kind: object["kind"] as? String,
                             question: object["question"] as? String,
                             options: object["options"] as? [String] ?? [])
        case "question":
            return .question(id: object["question_id"] as? String ?? "", prompt: object["prompt"] as? String ?? "",
                             choices: object["choices"] as? [String] ?? [])
        case "heartbeat":
            return .heartbeat
        case "message_end":
            return .messageEnd(runID: object["run_id"] as? String ?? "")
        case "cancelled":
            return .cancelled(runID: object["run_id"] as? String ?? "")
        case "artifact":
            return .artifact(name: object["name"] as? String ?? "file", mediaType: object["media_type"] as? String,
                             size: object["size"] as? Int ?? 0)
        case "artifact_rejected":
            return .artifactRejected(count: object["count"] as? Int ?? 0)
        case "model_routing":
            return .modelRouting(selected: object["selected_profile_id"] as? String)
        case "workflow_step":
            return .workflowStep(stepID: object["step_id"] as? String ?? "", action: object["action"] as? String,
                                 status: object["status"] as? String)
        case "workflow_run":
            return .workflowRun(status: object["status"] as? String)
        case "display_object":
            return .displayObject
        case "event_unavailable":
            return .eventUnavailable(reason: object["reason"] as? String)
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
