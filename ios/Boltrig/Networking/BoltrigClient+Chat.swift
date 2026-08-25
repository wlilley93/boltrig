import Foundation

extension BoltrigClient {
    /// A conversation's stored messages, plus whether a run is live on it.
    func conversation(id: String) async throws -> ConversationHistory {
        let (data, _) = try await perform(path: "/v1/conversations/\(id)", method: "GET", body: nil)
        return try ConversationHistory.decode(data)
    }

    func chatConfig() async throws -> AttachmentLimits {
        let (data, _) = try await perform(path: "/v1/chat/config", method: "GET", body: nil)
        return AttachmentLimits.decode(data)
    }

    func answerQuestion(id: String, answer: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["answer": answer])
        _ = try await perform(path: "/v1/hitl/\(id)/answer", method: "POST", body: body)
    }

    /// Soft-closes a conversation; it can be brought back.
    func closeConversation(id: String) async throws {
        _ = try await perform(path: "/v1/me/conversations/\(id)", method: "DELETE", body: nil)
    }

    func restoreConversation(id: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: [String: Any]())
        _ = try await perform(path: "/v1/me/conversations/\(id)/restore", method: "POST", body: body)
    }

    /// Re-attaches to a conversation's live run from a cursor. Yields `.idle` once and finishes
    /// when the server says nothing is running (409), which is the normal quiet answer.
    func follow(conversationID: String, since: Int) -> AsyncThrowingStream<FollowOutcome, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let path = "/v1/conversations/\(conversationID)/events?follow=1&since=\(max(0, since))"
                    var request = try makeRequest(path: path, method: "GET", body: nil, accept: "text/event-stream")
                    request.timeoutInterval = 600
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse else { throw BoltrigError(kind: .invalidResponse, status: 0) }
                    if http.statusCode == 409 {
                        _ = try await SSEByteReader.collect(bytes)
                        continuation.yield(.idle)
                        continuation.finish()
                        return
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        throw Self.mapError(status: http.statusCode, data: try await SSEByteReader.collect(bytes))
                    }
                    for try await frame in SSEByteReader.frames(from: bytes) {
                        let cursor = (frame["cursor"] as? Int) ?? Int((frame["cursor"] as? Double) ?? -1)
                        let eventObject = frame["event"] as? [String: Any] ?? [:]
                        continuation.yield(.frame(FollowFrame(
                            cursor: cursor,
                            event: ChatEvent.from(json: eventObject),
                            replayTruncated: frame["replay_truncated"] as? Bool ?? false
                        )))
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch let error as BoltrigError {
                    continuation.finish(throwing: error)
                } catch {
                    continuation.finish(throwing: BoltrigError(kind: .unreachable, status: 0))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
