import SwiftUI

@main
struct EzcanApp: App {
    @StateObject private var pairingStore = PairingStore()
    @StateObject private var sharedFileMonitor = SharedFileMonitor()
    @Environment(\.scenePhase) private var scenePhase
    @State private var previousCrash: CrashReport?
    @State private var sharedFilesPresented = false
    @State private var fileToOpen: SharedFileOpenItem?
    @State private var sharedFileError: String?

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
                .alert(item: $sharedFileMonitor.newlyReceivedFile) { file in
                    Alert(
                        title: Text("New file"),
                        message: Text("\(file.fileName) is ready on the computer."),
                        primaryButton: .default(Text("Open")) {
                            sharedFileMonitor.dismissNewFile()
                            downloadAndOpen(file)
                        },
                        secondaryButton: .cancel {
                            sharedFileMonitor.dismissNewFile()
                        }
                    )
                }
                .alert("File transfer failed", isPresented: Binding(
                    get: { sharedFileError != nil },
                    set: { if !$0 { sharedFileError = nil } }
                )) {
                    Button("OK", role: .cancel) {}
                } message: {
                    Text(sharedFileError ?? "The computer could not provide that file.")
                }
                .sheet(isPresented: $sharedFilesPresented) {
                    SharedFilesView()
                }
                .sheet(item: $fileToOpen) { item in
                    ShareSheet(fileURL: item.url)
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

    private func downloadAndOpen(_ file: SharedFile) {
        guard let pairing = pairingStore.pairing else { return }
        Task { @MainActor in
            do {
                let url = try await LocalReceiverClient(pairing: pairing).downloadSharedFile(file)
                fileToOpen = SharedFileOpenItem(url: url)
            } catch {
                sharedFileError = error.localizedDescription
            }
        }
    }
}

struct SharedFileOpenItem: Identifiable {
    let id = UUID()
    let url: URL
}
