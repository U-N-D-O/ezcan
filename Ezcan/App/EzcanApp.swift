import SwiftUI

@main
struct EzcanApp: App {
    @StateObject private var pairingStore = PairingStore()
    @StateObject private var sharedFileMonitor = SharedFileMonitor()
    @Environment(\.scenePhase) private var scenePhase
    @State private var previousCrash: CrashReport?
    @State private var sharedFilesPresented = false

    init() {
        CrashReporter.install()
        _previousCrash = State(initialValue: CrashReporter.shared.previousCrash())
        CrashReporter.shared.startSession()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(pairingStore)
                .environmentObject(sharedFileMonitor)
                .alert(item: $previousCrash) { report in
                    Alert(
                        title: Text("Ezcan recovered from a crash"),
                        message: Text(report.message),
                        dismissButton: .default(Text("OK"))
                    )
                }
                .alert("File received", item: $sharedFileMonitor.newlyReceivedFile) { file in
                    Button("View Files") {
                        sharedFileMonitor.dismissNewFile()
                        sharedFilesPresented = true
                    }
                    Button("OK", role: .cancel) {
                        sharedFileMonitor.dismissNewFile()
                    }
                } message: { file in
                    Text("\(file.fileName) is ready on the computer. Open Files to download it.")
                }
                .sheet(isPresented: $sharedFilesPresented) {
                    SharedFilesView()
                }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background {
                        CrashReporter.shared.markBackgrounded()
                    }
                }
                .task {
                    sharedFileMonitor.start(pairing: pairingStore.pairing)
                }
                .onChange(of: pairingStore.pairing) { _, pairing in
                    sharedFileMonitor.start(pairing: pairing)
                }
        }
    }
}
