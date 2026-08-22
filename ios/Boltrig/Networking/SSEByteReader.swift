import Foundation

/// Reads a server-sent event stream frame by frame. Lines are split by hand because
/// `AsyncBytes.lines` does not deliver the blank lines that end a frame.
struct SSEByteReader {
    /// Yields each decoded `data:` frame as a JSON object.
    static func frames(from bytes: URLSession.AsyncBytes) -> AsyncThrowingStream<[String: Any], Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var parser = SSEFrameParser()
                    var lineBuffer = Data()
                    for try await byte in bytes {
                        try Task.checkCancellation()
                        if byte == UInt8(ascii: "\n") {
                            if lineBuffer.last == UInt8(ascii: "\r") { lineBuffer.removeLast() }
                            let line = String(decoding: lineBuffer, as: UTF8.self)
                            lineBuffer.removeAll(keepingCapacity: true)
                            if let frame = parser.consume(line: line) { continuation.yield(frame) }
                        } else {
                            lineBuffer.append(byte)
                        }
                    }
                    if !lineBuffer.isEmpty {
                        if lineBuffer.last == UInt8(ascii: "\r") { lineBuffer.removeLast() }
                        if let frame = parser.consume(line: String(decoding: lineBuffer, as: UTF8.self)) {
                            continuation.yield(frame)
                        }
                    }
                    if let frame = parser.flush() { continuation.yield(frame) }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func collect(_ bytes: URLSession.AsyncBytes) async throws -> Data {
        var collected = Data()
        for try await byte in bytes { collected.append(byte) }
        return collected
    }
}
