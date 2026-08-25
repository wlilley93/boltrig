import UIKit
import XCTest
@testable import Boltrig

@MainActor
final class AttachmentTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.reset()
    }

    private func client() -> BoltrigClient {
        BoltrigClient(baseURL: BoltrigEnvironment.hostedInstanceURL, authorization: .accessToken("boltrig_pat_x"),
                      session: URLSession(configuration: Fixtures.stubbedConfiguration))
    }

    /// A square of noise: it compresses badly, so a modest side already passes the per-file limit.
    private func noisyPNG(side: Int) -> Data {
        var bytes = [UInt8](repeating: 0, count: side * side * 4)
        var x: UInt32 = 2_463_534_242
        for i in 0..<bytes.count {
            x ^= x << 13; x ^= x >> 17; x ^= x << 5
            bytes[i] = UInt8(truncatingIfNeeded: x)
        }
        let provider = CGDataProvider(data: Data(bytes) as CFData)!
        let cg = CGImage(width: side, height: side, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: side * 4,
                         space: CGColorSpaceCreateDeviceRGB(),
                         bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                         provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
        return UIImage(cgImage: cg).pngData()!
    }

    func testAPhotoOverTheLimitIsShrunkToFit() {
        let raw = noisyPNG(side: 1600)
        XCTAssertGreaterThan(raw.count, 256 * 1024)
        let outcome = AttachmentImporter.photo(raw, name: "Photo 1.jpg", limits: AttachmentLimits())
        guard case let .ready(attachment) = outcome else { return XCTFail("expected a fitted photo, got \(outcome)") }
        XCTAssertEqual(attachment.name, "Photo 1.jpg")
        XCTAssertEqual(attachment.mediaType, "image/jpeg")
        XCTAssertLessThanOrEqual(attachment.data.count, 256 * 1024)
        XCTAssertNotNil(UIImage(data: attachment.data))
    }

    func testAPhotoThatCannotFitIsRefusedWithTheSizeCopy() {
        var tiny = AttachmentLimits()
        tiny.maxBytes = 64
        XCTAssertEqual(AttachmentImporter.photo(noisyPNG(side: 400), name: "Photo 1.jpg", limits: tiny),
                       .refused("That file is too big to send here. The limit is \(ChatSession.size(64)) each."))
        XCTAssertEqual(AttachmentImporter.photo(Data([1, 2, 3]), name: "x.jpg", limits: AttachmentLimits()),
                       .refused("That photo could not be read."))
    }

    func testAFileOverTheLimitIsRefusedBeforeItIsRead() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let big = dir.appendingPathComponent("notes.txt")
        try Data(repeating: 0x41, count: 300 * 1024).write(to: big)
        XCTAssertEqual(AttachmentImporter.file(at: big, limits: AttachmentLimits()), .refused(AttachmentImporter.tooBig(AttachmentLimits())))
        let small = dir.appendingPathComponent("brief.md")
        try Data("# Brief\n".utf8).write(to: small)
        guard case let .ready(attachment) = AttachmentImporter.file(at: small, limits: AttachmentLimits()) else { return XCTFail("small file refused") }
        XCTAssertEqual(attachment.name, "brief.md")
        XCTAssertTrue(attachment.mediaType.hasPrefix("text/"), "markdown is a text type the server reads: \(attachment.mediaType)")
        XCTAssertEqual(attachment.data.count, 8)
        XCTAssertEqual(AttachmentImporter.mediaType(for: URL(fileURLWithPath: "/x/a.txt")), "text/plain")
        XCTAssertEqual(AttachmentImporter.mediaType(for: URL(fileURLWithPath: "/x/a.zq9unknown")), "application/octet-stream")
    }

    func testTheSessionHoldsTheLimitsAndShowsOneLine() {
        let chat = ChatSession(client: client())
        chat.attach(.ready(ChatAttachment(name: "a.txt", mediaType: "text/plain", data: Data(count: 10))))
        XCTAssertNil(chat.attachmentNotice)
        XCTAssertEqual(chat.attachments.count, 1)
        chat.attach(.ready(ChatAttachment(name: "b.txt", mediaType: "text/plain", data: Data(count: 300 * 1024))))
        XCTAssertEqual(chat.attachmentNotice, AttachmentImporter.tooBig(AttachmentLimits()))
        XCTAssertEqual(chat.attachments.count, 1)
        chat.attach(.refused("That photo could not be read."))
        XCTAssertEqual(chat.attachmentNotice, "That photo could not be read.")
        chat.removeAttachment(named: "a.txt")
        XCTAssertNil(chat.attachmentNotice)
        XCTAssertTrue(chat.attachments.isEmpty)
    }

    func testARejectedUploadShowsPlainCopy() async throws {
        StubURLProtocol.on("POST", "/v1/chat") { _ in StubURLProtocol.json(413, ["error": "attachment_rejected"]) }
        let chat = ChatSession(client: client())
        chat.attach(.ready(ChatAttachment(name: "a.txt", mediaType: "text/plain", data: Data("hi".utf8))))
        await chat.sendMessage("Read this")
        XCTAssertEqual(chat.messages.last?.content, ChatSession.attachmentsRejectedCopy)
        XCTAssertTrue(chat.turnFailed)
        XCTAssertTrue(chat.attachments.isEmpty, "the files left the composer with the message")
        let body = StubURLProtocol.body(of: StubURLProtocol.recorded("POST", "/v1/chat")[0])
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        let sent = try XCTUnwrap(object["attachments"] as? [[String: Any]])
        XCTAssertEqual(sent.first?["name"] as? String, "a.txt")
        XCTAssertEqual(sent.first?["media_type"] as? String, "text/plain")
    }
}
