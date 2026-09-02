import SwiftUI
import UIKit

struct SharedFilesView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @EnvironmentObject private var sharedFileMonitor: SharedFileMonitor
    @Environment(\.dismiss) private var dismiss
    @State private var files: [SharedFile] = []
    @State private var isLoading = false
    @State private var downloadingID: String?
    @State private var errorMessage: String?
    @State private var shareItem: ShareItem?

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 18) {
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
                .padding(.top, 72)
                .padding(.bottom, 18)
            }
            .background(EzcanBackground())
            .toolbar(.hidden, for: .navigationBar)
            .overlay(alignment: .topTrailing) {
                Button(action: dismiss.callAsFunction) {
                    Image(systemName: "xmark")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(EzcanTheme.muted)
                        .frame(width: 34, height: 34)
                        .background(EzcanTheme.white.opacity(0.82), in: Circle())
                        .overlay { Circle().stroke(EzcanTheme.line, lineWidth: 1) }
                }
                .accessibilityLabel("Close")
                .padding(.top, 18)
                .padding(.trailing, 18)
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
            .onAppear {
                sharedFileMonitor.isFilesPageVisible = true
            }
            .onDisappear {
                sharedFileMonitor.isFilesPageVisible = false
            }
            .onChange(of: sharedFileMonitor.files) { _, newFiles in
                files = newFiles
            }
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
        return Button {
            download(file)
        } label: {
            HStack(spacing: 14) {
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
                if downloadingID == file.id {
                    ProgressView().tint(EzcanTheme.ink)
                } else {
                    Image(systemName: "arrow.up.forward.app")
                        .font(.headline)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(downloadingID != nil)
        .accessibilityLabel("Open \(file.fileName)")
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
                shareItem = ShareItem(url: url)
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

struct ShareSheet: UIViewControllerRepresentable {
    let fileURL: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [fileURL], applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
