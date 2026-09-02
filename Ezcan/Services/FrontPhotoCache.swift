import Foundation

enum FrontPhotoCache {
    private static let directoryName = "Ezcan"
    private static let filePrefix = "front-"

    static func cache(media: CapturedMedia, intakeID: String) -> URL? {
        guard let directory = directoryURL() else { return nil }
        let destination = directory.appendingPathComponent("\(filePrefix)\(intakeID).jpg")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: destination)
            try FileManager.default.copyItem(at: media.fileURL, to: destination)
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
}
