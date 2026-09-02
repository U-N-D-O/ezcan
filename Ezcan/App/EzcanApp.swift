import SwiftUI

@main
struct EzcanApp: App {
    @StateObject private var pairingStore = PairingStore()
    @Environment(\.scenePhase) private var scenePhase
    @State private var previousCrash: CrashReport?

    init() {
        CrashReporter.install()
        _previousCrash = State(initialValue: CrashReporter.shared.previousCrash())
        CrashReporter.shared.startSession()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(pairingStore)
                .alert(item: $previousCrash) { report in
                    Alert(
                        title: Text("Ezcan recovered from a crash"),
                        message: Text(report.message),
                        dismissButton: .default(Text("OK"))
                    )
                }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background {
                        CrashReporter.shared.markBackgrounded()
                    }
                }
        }
    }
}
