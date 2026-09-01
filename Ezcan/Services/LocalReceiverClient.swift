import CryptoKit
import Foundation

struct CapturedMedia: Identifiable, Equatable {
    enum Kind: String, Equatable {
        case image
        case video
    }

    let id: UUID
    let fileURL: URL
    let kind: Kind
    let fileName: String

    init(id: UUID = UUID(), fileURL: URL, kind: Kind, fileName: String) {
        self.id = id
        self.fileURL = fileURL
        self.kind = kind
        self.fileName = fileName
    }

    func named(_ fileName: String) -> CapturedMedia {
        CapturedMedia(id: id, fileURL: fileURL, kind: kind, fileName: fileName)
    }
}

struct IntakeReceipt: Decodable {
    let intakeId: String
    let suggestedArchiveCode: String?
}

struct ArchiveReceipt: Decodable {
    let archiveCode: String
}

struct SharedFile: Decodable, Identifiable, Equatable {
    let fileName: String
    let size: Int
    let modifiedAt: String

    var id: String { fileName }
}

struct LocalReceiverClient {
    let pairing: PairingCode

    func createIntake(note: String?) async throws -> IntakeReceipt {
        let request = try makeRequest(path: "api/intakes", method: "POST", contentType: "application/json")
        var mutableRequest = request
        let payload = ["note": note ?? ""]
        let body = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await URLSession.shared.upload(for: mutableRequest, from: body)
        try validate(response)
        return try JSONDecoder().decode(IntakeReceipt.self, from: data)
    }

    func upload(_ media: CapturedMedia, to intakeId: String) async throws {
        let hash = try sha256(of: media.fileURL)
        var request = try makeRequest(
            path: "api/intakes/\(intakeId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? intakeId)/media",
            method: "POST",
            contentType: media.kind == .image ? "image/jpeg" : "video/quicktime"
        )
        request.setValue(media.fileName, forHTTPHeaderField: "X-Ezcan-File-Name")
        request.setValue(media.kind.rawValue, forHTTPHeaderField: "X-Ezcan-Media-Type")
        request.setValue(hash, forHTTPHeaderField: "X-Ezcan-SHA256")
        let (_, response) = try await URLSession.shared.upload(for: request, fromFile: media.fileURL)
        try validate(response)
    }

    func completeIntake(_ intakeId: String) async throws -> ArchiveReceipt {
        try await completeIntake(intakeId, archiveCode: nil)
    }

    func completeIntake(_ intakeId: String, archiveCode: String?) async throws -> ArchiveReceipt {
        let request = try makeRequest(
            path: "api/intakes/\(intakeId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? intakeId)/complete",
            method: "POST",
            contentType: "application/json"
        )
        var payload: [String: String] = [:]
        if let archiveCode {
            payload["archiveCode"] = archiveCode
        }
        let body = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        try validate(response)
        return try JSONDecoder().decode(ArchiveReceipt.self, from: data)
    }

    func listSharedFiles() async throws -> [SharedFile] {
        let request = try makeRequest(path: "api/shared-files", method: "GET", contentType: "application/json")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        let envelope = try JSONDecoder().decode(SharedFileEnvelope.self, from: data)
        return envelope.files
    }

    func downloadSharedFile(_ file: SharedFile) async throws -> URL {
        let encodedName = file.fileName.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? file.fileName
        let request = try makeRequest(path: "api/shared-files/\(encodedName)", method: "GET", contentType: "application/octet-stream")
        let (temporaryURL, response) = try await URLSession.shared.download(for: request)
        try validate(response)
        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent("Ezcan-\(file.fileName)")
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: temporaryURL, to: destination)
        return destination
    }

    private struct SharedFileEnvelope: Decodable {
        let files: [SharedFile]
    }

    private func makeRequest(path: String, method: String, contentType: String) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: pairing.url)?.absoluteURL else {
            throw ReceiverError.invalidEndpoint
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 60
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(pairing.token)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func validate(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode) else {
            throw ReceiverError.serverRejected
        }
    }

    private func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var digest = SHA256()
        while autoreleasepool(invoking: {
            let chunk = handle.readData(ofLength: 1024 * 1024)
            guard !chunk.isEmpty else { return false }
            digest.update(data: chunk)
            return true
        }) {}
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

enum ReceiverError: LocalizedError {
    case invalidEndpoint
    case serverRejected

    var errorDescription: String? {
        switch self {
        case .invalidEndpoint:
            return "The paired computer address is invalid."
        case .serverRejected:
            return "The computer rejected the request. Check its logs and try again."
        }
    }
}
