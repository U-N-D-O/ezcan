import Foundation
import ImageIO

enum FrontPhotoCache {
    private static let directoryName = "Ezcan"
    private static let filePrefix = "front-"
    private static let pictureRegion = CGRect(x: 0.055, y: 0.08, width: 0.805, height: 0.435)

    static func cache(media: CapturedMedia, intakeID: String) -> URL? {
        guard let directory = directoryURL() else { return nil }
        let destination = directory.appendingPathComponent("\(filePrefix)\(intakeID).jpg")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: destination)
                        guard let source = CGImageSourceCreateWithURL(media.fileURL as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
                                    let image = CGImageSourceCreateThumbnailAtIndex(
                                        source,
                                        0,
                                        [
                                                kCGImageSourceCreateThumbnailFromImageAlways: true,
                                                kCGImageSourceCreateThumbnailWithTransform: true,
                                                kCGImageSourceShouldCache: false,
                                                kCGImageSourceThumbnailMaxPixelSize: 2400
                                        ] as CFDictionary
                                    ),
                                    let picture = crop(image, to: pictureRegion),
                                    let output = jpegData(for: picture) else {
                                return nil
                        }
                        try output.write(to: destination, options: .atomic)
            return destination
        } catch {
            return nil
        }
    }

    static func remove(_ url: URL?) {
        guard let url else { return }
        try? FileManager.default.removeItem(at: url)
    }

    static func removeStalePhotos() {
        guard let directory = directoryURL(),
              let contents = try? FileManager.default.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
              ) else {
            return
        }

        for url in contents where isCachedFrontPhoto(url) {
            try? FileManager.default.removeItem(at: url)
        }
    }

    private static func directoryURL() -> URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent(directoryName, isDirectory: true)
    }

    private static func isCachedFrontPhoto(_ url: URL) -> Bool {
        url.lastPathComponent.hasPrefix(filePrefix) && url.pathExtension.lowercased() == "jpg"
    }

    private static func crop(_ image: CGImage, to normalizedRect: CGRect) -> CGImage? {
        let pixelRect = CGRect(
            x: normalizedRect.minX * CGFloat(image.width),
            y: normalizedRect.minY * CGFloat(image.height),
            width: normalizedRect.width * CGFloat(image.width),
            height: normalizedRect.height * CGFloat(image.height)
        ).integral.intersection(CGRect(x: 0, y: 0, width: image.width, height: image.height))
        guard pixelRect.width > 32, pixelRect.height > 32 else { return nil }
        return image.cropping(to: pixelRect)
    }

    private static func jpegData(for image: CGImage) -> Data? {
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, "public.jpeg" as CFString, 1, nil) else {
            return nil
        }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.96] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }
}
