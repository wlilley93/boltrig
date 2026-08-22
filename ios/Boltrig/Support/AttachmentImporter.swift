import Foundation
import UIKit
import UniformTypeIdentifiers

/// Turns what the person picked into an attachment the server accepts, or says plainly why it cannot.
enum AttachmentImporter {
    enum Outcome: Equatable {
        case ready(ChatAttachment)
        case refused(String)
    }

    /// Reads a file the person chose. The size is checked before any bytes are read, so a large
    /// file never fills memory on its way to a refusal.
    static func file(at url: URL, limits: AttachmentLimits) -> Outcome {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max
        if size > limits.maxBytes { return .refused(tooBig(limits)) }
        guard let data = try? Data(contentsOf: url) else { return .refused("That file could not be read.") }
        if data.count > limits.maxBytes { return .refused(tooBig(limits)) }
        return .ready(ChatAttachment(name: url.lastPathComponent, mediaType: mediaType(for: url), data: data))
    }

    /// Re-encodes a photo as JPEG, shrinking it until it fits the per-file limit, or refuses when
    /// even a small copy is over it.
    static func photo(_ raw: Data, name: String, limits: AttachmentLimits) -> Outcome {
        guard let image = UIImage(data: raw) else { return .refused("That photo could not be read.") }
        guard let fitted = jpeg(image, under: limits.maxBytes) else { return .refused(tooBig(limits)) }
        return .ready(ChatAttachment(name: name, mediaType: "image/jpeg", data: fitted))
    }

    /// Lower quality first, then a smaller picture; stops at 160 px on the long side.
    static func jpeg(_ image: UIImage, under limit: Int) -> Data? {
        var current = image
        var longest = max(image.size.width, image.size.height) * image.scale
        for _ in 0..<10 {
            for quality in [0.82, 0.6, 0.4] {
                if let data = current.jpegData(compressionQuality: quality), data.count <= limit { return data }
            }
            longest = floor(longest * 0.7)
            if longest < 160 { return nil }
            current = resized(current, longestSide: longest)
        }
        return nil
    }

    static func resized(_ image: UIImage, longestSide: CGFloat) -> UIImage {
        let pixelWidth = image.size.width * image.scale
        let pixelHeight = image.size.height * image.scale
        let ratio = longestSide / max(pixelWidth, pixelHeight)
        let target = CGSize(width: max(1, floor(pixelWidth * ratio)), height: max(1, floor(pixelHeight * ratio)))
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
    }

    static func mediaType(for url: URL) -> String {
        if let type = UTType(filenameExtension: url.pathExtension), let mime = type.preferredMIMEType { return mime }
        return "application/octet-stream"
    }

    static func tooBig(_ limits: AttachmentLimits) -> String {
        "That file is too big to send here. The limit is \(ChatSession.size(limits.maxBytes)) each."
    }
}
