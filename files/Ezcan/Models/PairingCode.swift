import Foundation

struct PairingCode: Codable, Equatable {
    let version: Int
    let url: URL
    let token: String
    let computerName: String?

    init(version: Int = 1, url: URL, token: String, computerName: String? = nil) throws {
        guard let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" else {
            throw PairingError.invalidURL
        }
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw PairingError.emptyToken
        }
        self.version = version
        self.url = url
        self.token = token
        self.computerName = computerName
    }

    static func decode(_ text: String) throws -> PairingCode {
        let data = Data(text.utf8)
        let decoded = try JSONDecoder().decode(PairingPayload.self, from: data)
        guard decoded.protocolName == "ezcan", decoded.version == 1 else {
            throw PairingError.unsupportedPayload
        }
        return try PairingCode(
            version: decoded.version,
            url: decoded.url,
            token: decoded.token,
            computerName: decoded.computerName
        )
    }

    private struct PairingPayload: Decodable {
        let protocolName: String
        let version: Int
        let url: URL
        let token: String
        let computerName: String?

        enum CodingKeys: String, CodingKey {
            case protocolName = "protocol"
            case version
            case url
            case token
            case computerName
        }
    }
}

enum PairingError: LocalizedError {
    case invalidURL
    case emptyToken
    case unsupportedPayload

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Enter a valid http or https computer address."
        case .emptyToken:
            return "A pairing token is required."
        case .unsupportedPayload:
            return "This is not a supported Ezcan pairing code."
        }
    }
}
