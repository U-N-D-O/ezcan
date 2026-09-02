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
                            .foregroundStyle(EzcanTheme.text)
                    } else if files.isEmpty {
                        ContentUnavailableView(
                            "NO FILES READY",
                            systemImage: "tray",
                            description: Text("Choose a file in the Ezcan Computer window first.")
                        )
                        .foregroundStyle(EzcanTheme.muted)
                    } else {
                        List(files) { file in
                            HStack(spacing: 14) {
                                Image(systemName: file.fileName.lowercased().hasSuffix(".ipa") ? "iphone.gen3" : "doc.fill")
                                    .font(.title3)
                                    .foregroundStyle(file.fileName.lowercased().hasSuffix(".ipa") ? EzcanTheme.blue : EzcanTheme.amber)
                                    .frame(width: 38, height: 38)
                                    .background(EzcanTheme.panelDeep, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                                    .overlay { RoundedRectangle(cornerRadius: 10).stroke(EzcanTheme.border, lineWidth: 1) }
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(file.fileName)
                                        .font(.headline)
                                        .foregroundStyle(EzcanTheme.text)
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
                                        ProgressView()
                                            .tint(.white)
                                    } else {
                                        Image(systemName: "arrow.down.to.line")
                                    }
                                }
                                .buttonStyle(.borderedProminent)
                                .tint(EzcanTheme.blue)
                                .disabled(downloadingID != nil)
                                .accessibilityLabel("Download \(file.fileName)")
                            }
                            .padding(.vertical, 7)
                            .listRowBackground(EzcanTheme.panel.opacity(0.94))
                            .listRowSeparator(.hidden)
                        }
                        .scrollContentBackground(.hidden)
                        .listStyle(.insetGrouped)
                    }
                }
            }
            .navigationTitle("FILES FROM COMPUTER")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(EzcanTheme.deep.opacity(0.92), for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
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