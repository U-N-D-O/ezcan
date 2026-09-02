import Foundation

@MainActor
final class SharedFileMonitor: ObservableObject {
    @Published private(set) var files: [SharedFile] = []
    @Published var isFilesPageVisible = false
    @Published var newlyReceivedFile: SharedFile?

    private var pollingTask: Task<Void, Never>?
    private var knownFileNames = Set<String>()
    private var hasLoadedInitialFiles = false
    private var pairing: PairingCode?

    func start(pairing: PairingCode?) {
        guard self.pairing?.url != pairing?.url || self.pairing?.token != pairing?.token else { return }
        stop()
        self.pairing = pairing
        guard let pairing else { return }

        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.poll(pairing: pairing)
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func stop() {
        pollingTask?.cancel()
        pollingTask = nil
        pairing = nil
        files = []
        knownFileNames = []
        hasLoadedInitialFiles = false
        newlyReceivedFile = nil
    }

    func dismissNewFile() {
        newlyReceivedFile = nil
    }

    private func poll(pairing: PairingCode) async {
        do {
            let currentFiles = try await LocalReceiverClient(pairing: pairing).listSharedFiles()
            guard !Task.isCancelled else { return }
            files = currentFiles
            let currentNames = Set(currentFiles.map(\.fileName))
            if hasLoadedInitialFiles {
                let newFile = currentFiles.first { !knownFileNames.contains($0.fileName) }
                if !isFilesPageVisible, let newFile {
                    newlyReceivedFile = newFile
                }
            } else {
                hasLoadedInitialFiles = true
            }
            knownFileNames = currentNames
        } catch {
            // The Files page displays request errors when opened.
        }
    }
}