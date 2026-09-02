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

    var body: some View {
        NavigationStack {
            ZStack {
                EzcanBackground()
                Group {
                    if isLoading && files.isEmpty {
                        ProgressView("CHECKING COMPUTER...")
                            .tint(EzcanTheme.cyan)
                            .foregroundStyle(EzcanTheme.ink)
                    } else if files.isEmpty {
                        ContentUnavailableView(
                            "No files ready",
                            systemImage: "tray",
                            description: Text("Choose a file in Ezcan Computer first.")
                        )
                        .foregroundStyle(EzcanTheme.muted)
                    } else {
                        ScrollView(showsIndicators: false) {
                            VStack(spacing: 12) {
                                ForEach(files) { file in
                                    fileCard(file)
                                }
                            }
                            .padding(.horizontal, 20)
                            .padding(.vertical, 18)
                        }
                    }
                }
            }
            .navigationTitle("Files from computer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(EzcanTheme.canvas, for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
            .tint(EzcanTheme.cyan)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                    }
                    .accessibilityLabel("Done")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await refresh() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(isLoading)
                    .accessibilityLabel("Refresh files")
                }
            }
            .alert("File transfer failed", isPresented: Binding(
                get: { errorMessage != nil },
                set: { if !$0 { errorMessage = nil } }
            )) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(errorMessage ?? "The computer could not provide that file.")
            }
            .task { await refresh() }
            .sheet(item: $shareItem) { item in
                ShareSheet(fileURL: item.url)
            }
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
                shareItem = ShareItem(url: try await LocalReceiverClient(pairing: pairing).downloadSharedFile(file))
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