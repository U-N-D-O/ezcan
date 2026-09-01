import SwiftUI

@main
struct EzcanApp: App {
    @StateObject private var pairingStore = PairingStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(pairingStore)
        }
    }
}
