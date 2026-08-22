import Foundation

/// One stored message of a conversation, as `GET /v1/conversations/{id}` returns it.
struct StoredMessage: Identifiable, Equatable {
    enum Role: String { case user, assistant, other }

    let id: String
    let role: Role
    let content: String
    let runID: String?
    let hitlRequestID: String?
    let attachments: [StoredAttachment]
    let supersededBy: String?
    let createdAt: String

    static func decode(_ object: [String: Any]) -> StoredMessage? {
        guard let id = object["id"] as? String else { return nil }
        let roleValue = (object["role"] as? String ?? "").lowercased()
        let role: Role = roleValue == "user" ? .user : (roleValue == "assistant" ? .assistant : .other)
        let attachments = (object["attachments"] as? [[String: Any]] ?? []).compactMap(StoredAttachment.decode)
        return StoredMessage(
            id: id,
            role: role,
            content: object["content"] as? String ?? "",
            runID: object["run_id"] as? String,
            hitlRequestID: object["hitl_request_id"] as? String,
            attachments: attachments,
            supersededBy: object["superseded_by"] as? String,
            createdAt: object["created_at"] as? String ?? ""
        )
    }
}

struct StoredAttachment: Equatable {
    let name: String
    let mediaType: String
    let size: Int

    static func decode(_ object: [String: Any]) -> StoredAttachment? {
        StoredAttachment(name: object["name"] as? String ?? "attachment",
                         mediaType: object["media_type"] as? String ?? "application/octet-stream",
                         size: object["size"] as? Int ?? 0)
    }
}

/// A conversation with its history and whether a run is live right now.
struct ConversationHistory: Equatable {
    let id: String
    let title: String
    let status: String
    let messages: [StoredMessage]
    let activeRunID: String?
    let queuedMessageIDs: [String]

    static func decode(_ data: Data) throws -> ConversationHistory {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let conversation = root["conversation"] as? [String: Any],
              let id = conversation["id"] as? String else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        return ConversationHistory(
            id: id,
            title: conversation["title"] as? String ?? "",
            status: conversation["status"] as? String ?? "",
            messages: (root["messages"] as? [[String: Any]] ?? []).compactMap(StoredMessage.decode),
            activeRunID: root["active_run_id"] as? String,
            queuedMessageIDs: root["queued_message_ids"] as? [String] ?? []
        )
    }
}

/// What a file attached to a message carries over the wire.
struct ChatAttachment: Equatable {
    let name: String
    let mediaType: String
    let data: Data

    var wireForm: [String: Any] {
        ["name": name, "media_type": mediaType, "data": data.base64EncodedString()]
    }
}

/// The limits the server applies to attachments, from `GET /v1/chat/config`. The code
/// defaults apply when the route cannot be read; a deployment can only tighten them.
struct AttachmentLimits: Equatable {
    var maxCount: Int = 8
    var maxBytes: Int = 256 * 1024
    var maxTotalBytes: Int = 1024 * 1024
    var readableTypes: [String] = ["text/*"]

    static func decode(_ data: Data) -> AttachmentLimits {
        var limits = AttachmentLimits()
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let attachments = root["attachments"] as? [String: Any] else { return limits }
        if let value = attachments["max_count"] as? Int { limits.maxCount = value }
        if let value = attachments["max_bytes"] as? Int { limits.maxBytes = value }
        if let value = attachments["max_total_bytes"] as? Int { limits.maxTotalBytes = value }
        if let value = attachments["model_readable_media_types"] as? [String] { limits.readableTypes = value }
        return limits
    }
}

/// One frame of a followed run: the cursor to resume from and the event it carried.
struct FollowFrame: Equatable {
    let cursor: Int
    let event: ChatEvent
    let replayTruncated: Bool
}

enum FollowOutcome: Equatable {
    case frame(FollowFrame)
    /// 409 from the server: nothing is running. Not an error.
    case idle
}
