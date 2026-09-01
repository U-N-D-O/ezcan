import Foundation
import SwiftUI

@MainActor
final class PairingStore: ObservableObject {
    @Published private(set) var pairing: PairingCode?
    @Published var errorMessage: String?

    private let storageKey = "ezcan.pairing"

    init() {
        load()
    }

    var isPaired: Bool {
        pairing != nil
    }

    func pair(with code: PairingCode) {
        pairing = code
        errorMessage = nil
        if let data = try? JSONEncoder().encode(code) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }

    func unpair() {
        pairing = nil
        UserDefaults.standard.removeObject(forKey: storageKey)
    }

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let savedPairing = try? JSONDecoder().decode(PairingCode.self, from: data) else {
            return
        }
        pairing = savedPairing
    }
}
