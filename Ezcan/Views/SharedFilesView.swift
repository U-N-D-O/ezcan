import SwiftUI
import UIKit

struct SharedFilesView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @Environment(\.dismiss) private var dismiss
    @State private var files: [SharedFile] = []
    @State private var isLoading = false
    @State private var downloadingID: String?
    @State private var errorMessage: String?
    @State private var shareItem: ShareItem?
    @State private var receivedFile: ReceivedFile?

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 18) {
                    EzcanConsoleBar(section: "FILES", statusTitle: isLoading ? "SYNCING" : "ONLINE", trailingAction: { dismiss() })
                    VStack(spacing: 14) {
                        EzcanInstrumentRing(progress: files.isEmpty ? 0.12 : 0.72, accent: EzcanTheme.blue) {
                            VStack(spacing: 5) {
                                Text("\(files.count)")
                                    .font(.system(size: 28, weight: .black, design: .rounded))
                                    .foregroundStyle(EzcanTheme.blue)
                                Text(files.count == 1 ? "FILE READY" : "FILES READY")
                                    .font(.system(size: 9, weight: .black, design: .monospaced))
                                    .foregroundStyle(EzcanTheme.ink)
                            }
                        }
                        VStack(spacing: 8) {
                            Text("COMPUTER LIBRARY")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(EzcanTheme.muted)
                            Text("Ready to move")
                                .font(.title2.bold())
                                .foregroundStyle(EzcanTheme.ink)
                            Text("Download shared files from the connected workstation.")
                                .font(.subheadline)
                                .foregroundStyle(EzcanTheme.muted)
                            Button {
                                Task { await refresh() }
                            } label: {
                                Label("Refresh", systemImage: "arrow.clockwise")
                                    .font(.subheadline.weight(.semibold))
                            }
                            .buttonStyle(EzcanSecondaryButtonStyle())
                            .disabled(isLoading)
                        }
                        .multilineTextAlignment(.center)
                    }
                    .padding(20)
                    .frame(maxWidth: .infinity)
                    .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
                    .shadow(color: EzcanTheme.shadow, radius: 14, y: 7)
                    if isLoading && files.isEmpty {
                        ProgressView("Checking computer...")
                            .tint(EzcanTheme.cyan)
                            .foregroundStyle(EzcanTheme.ink)
                            .padding(.vertical, 35)
                    } else if files.isEmpty {
                        emptyState
                    } else {
                        VStack(spacing: 12) {
                            ForEach(files) { file in
                                fileCard(file)
                            }
                        }
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 18)
            }
            .background(EzcanBackground())
            .toolbar(.hidden, for: .navigationBar)
            .alert("File transfer failed", isPresented: Binding(
                get: { errorMessage != nil },
                set: { if !$0 { errorMessage = nil } }
            )) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(errorMessage ?? "The computer could not provide that file.")
            }
            .alert(item: $receivedFile) { file in
                Alert(
                    title: Text("File received"),
                    message: Text("\(file.fileName) is ready. Open it in the Files app or dismiss this message."),
                    primaryButton: .default(Text("Open in Files")) {
                        shareItem = ShareItem(url: file.url)
                    },
                    secondaryButton: .cancel(Text("OK"))
                )
            }
            .task { await refresh() }
            .sheet(item: $shareItem) { item in
                ShareSheet(fileURL: item.url)
            }
        }
    }

    private var emptyState: some View {
        EzcanSoftControl(tint: EzcanTheme.line) {
            VStack(spacing: 8) {
                Image(systemName: "tray")
                    .font(.title2)
                    .foregroundStyle(EzcanTheme.muted)
                Text("NO FILES READY")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(EzcanTheme.ink)
                Text("Choose a file in Ezcan Computer first.")
                    .font(.caption)
                    .foregroundStyle(EzcanTheme.muted)
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func fileCard(_ file: SharedFile) -> some View {
        let isIPA = file.fileName.lowercased().hasSuffix(".ipa")
        return HStack(spacing: 14) {
            Image(systemName: isIPA ? "iphone.gen3" : "doc.fill")
                .font(.title3)
                .foregroundStyle(isIPA ? EzcanTheme.cyan : EzcanTheme.amber)
                .frame(width: 46, height: 46)
                .background((isIPA ? EzcanTheme.cyan : EzcanTheme.amber).opacity(0.12), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(file.fileName)
                    .font(.headline)
                    .foregroundStyle(EzcanTheme.ink)
                    .lineLimit(1)
                Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
                    .font(.caption)
                    .foregroundStyle(EzcanTheme.muted)
            }
            Spacer()
            Button {
                download(file)
            } label: {
                if downloadingID == file.id {
                    ProgressView().tint(EzcanTheme.ink)
                } else {
                    Image(systemName: "arrow.down.to.line")
                        .font(.headline)
                }
            }
            .foregroundStyle(EzcanTheme.ink)
            .frame(width: 42, height: 42)
            .background(EzcanTheme.greenSoft, in: Circle())
            .overlay { Circle().stroke(EzcanTheme.green.opacity(0.35), lineWidth: 1) }
            .disabled(downloadingID != nil)
            .accessibilityLabel("Download \(file.fileName)")
        }
        .padding(16)
        .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: EzcanTheme.shadow, radius: 12, y: 6)
    }

    private func refresh() async {
        guard let pairing = pairingStore.pairing else { return }
        isLoading = true
        do {
            files = try await LocalReceiverClient(pairing: pairing).listSharedFiles()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func download(_ file: SharedFile) {
        guard let pairing = pairingStore.pairing else { return }
        downloadingID = file.id
        Task {
            do {
                let url = try await LocalReceiverClient(pairing: pairing).downloadSharedFile(file)
                receivedFile = ReceivedFile(fileName: file.fileName, url: url)
            } catch {
                errorMessage = error.localizedDescription
            }
            downloadingID = nil
        }
    }
}

private struct ShareItem: Identifiable {
    let id = UUID()
    let url: URL
}

private struct ShareSheet: UIViewControllerRepresentable {
    let fileURL: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [fileURL], applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

private struct ReceivedFile: Identifiable {
    let id = UUID()
    let fileName: String
    let url: URL
}