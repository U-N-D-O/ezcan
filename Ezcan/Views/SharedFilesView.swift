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
            Group {
                if isLoading && files.isEmpty {
                    ProgressView("Checking computer...")
                } else if files.isEmpty {
                    ContentUnavailableView(
                        "No files ready",
                        systemImage: "tray",
                        description: Text("Choose a file in the Ezcan Computer window first.")
                    )
                } else {
                    List(files) { file in
                        HStack(spacing: 14) {
                            Image(systemName: file.fileName.lowercased().hasSuffix(".ipa") ? "iphone.gen3" : "doc.fill")
                                .font(.title3)
                                .foregroundStyle(file.fileName.lowercased().hasSuffix(".ipa") ? .blue : .orange)
                                .frame(width: 38, height: 38)
                                .background(.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 10))
                            VStack(alignment: .leading, spacing: 4) {
                                Text(file.fileName)
                                    .font(.headline)
                                    .lineLimit(1)
                                Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button {
                                download(file)
                            } label: {
                                if downloadingID == file.id {
                                    ProgressView()
                                } else {
                                    Image(systemName: "arrow.down.to.line")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(downloadingID != nil)
                            .accessibilityLabel("Download \(file.fileName)")
                        }
                        .padding(.vertical, 5)
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Files from computer")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
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