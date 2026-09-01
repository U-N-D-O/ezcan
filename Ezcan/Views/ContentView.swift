import AVFoundation
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject private var pairingStore: PairingStore

    var body: some View {
        Group {
            if pairingStore.isPaired {
                DashboardView()
            } else {
                PairingView()
            }
        }
    }
}

struct PairingView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @State private var computerURL = "http://"
    @State private var token = ""
    @State private var computerName = ""
    @State private var qrPayload = ""
    @State private var showingScanner = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Image("ezcan_logo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 128, height: 128)
                        .frame(maxWidth: .infinity)
                    Text("Connect Ezcan to the computer on your private Wi-Fi network.")
                        .frame(maxWidth: .infinity)
                        .multilineTextAlignment(.center)
                }

                Section("Pairing") {
                    Button {
                        showingScanner = true
                    } label: {
                        Label("Scan computer QR code", systemImage: "qrcode.viewfinder")
                    }

                    TextField("Computer address", text: $computerURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    TextField("Pairing token", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Computer name (optional)", text: $computerName)
                    Button("Pair computer") {
                        pairManually()
                    }
                    .disabled(token.isEmpty || computerURL == "http://")
                }

                if let errorMessage = pairingStore.errorMessage {
                    Section {
                        Label(errorMessage, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Welcome to Ezcan")
            .sheet(isPresented: $showingScanner) {
                QRScannerView { payload in
                    qrPayload = payload
                    showingScanner = false
                    pairFromPayload()
                } onCancel: {
                    showingScanner = false
                }
            }
        }
    }

    private func pairManually() {
        guard let url = URL(string: computerURL) else {
            pairingStore.errorMessage = PairingError.invalidURL.localizedDescription
            return
        }
        do {
            pairingStore.pair(with: try PairingCode(url: url, token: token, computerName: computerName.isEmpty ? nil : computerName))
        } catch {
            pairingStore.errorMessage = error.localizedDescription
        }
    }

    private func pairFromPayload() {
        do {
            pairingStore.pair(with: try PairingCode.decode(qrPayload))
        } catch {
            pairingStore.errorMessage = error.localizedDescription
        }
    }
}

struct DashboardView: View {
    @EnvironmentObject private var pairingStore: PairingStore

    var body: some View {
        NavigationStack {
            List {
                Section("Connected computer") {
                    Label(pairingStore.pairing?.computerName ?? pairingStore.pairing?.url.host ?? "Computer", systemImage: "desktopcomputer")
                    Text(pairingStore.pairing?.url.absoluteString ?? "")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    NavigationLink {
                        NewCardView()
                    } label: {
                        Label("New card", systemImage: "plus.viewfinder")
                    }
                }

                Section {
                    Button("Disconnect computer", role: .destructive) {
                        pairingStore.unpair()
                    }
                }
            }
            .navigationTitle("Ezcan")
        }
    }
}

struct NewCardView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @State private var media: [CapturedMedia] = []
    @State private var note = ""
    @State private var showingCamera = false
    @State private var cameraType: UTType = .image
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var isUploading = false
    @State private var uploadMessage: String?

    var body: some View {
        Form {
            Section {
                Text("Keep one card per intake. Add a front photo, back photo, detail photos, and an optional surface video.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Section("Capture") {
                Button {
                    cameraType = .image
                    showingCamera = true
                } label: {
                    Label("Take photo", systemImage: "camera")
                }
                Button {
                    cameraType = .movie
                    showingCamera = true
                } label: {
                    Label("Record video", systemImage: "video")
                }
                PhotosPicker(selection: $selectedPhotos, matching: .any(of: [.images, .videos])) {
                    Label("Choose from Photos", systemImage: "photo.on.rectangle")
                }
                .onChange(of: selectedPhotos) { _, items in
                    Task { await importPhotos(items) }
                }
            }

            if !media.isEmpty {
                Section("Media (\(media.count))") {
                    ForEach(media) { item in
                        Label(item.fileName, systemImage: item.kind == .image ? "photo" : "video")
                    }
                    .onDelete { offsets in
                        media.remove(atOffsets: offsets)
                    }
                }
            }

            Section("Note") {
                TextField("Optional condition or handling note", text: $note, axis: .vertical)
            }

            Section {
                Button {
                    Task { await uploadIntake() }
                } label: {
                    if isUploading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Send to computer", systemImage: "arrow.up.circle.fill")
                            .frame(maxWidth: .infinity)
                    }
                }
                .disabled(media.isEmpty || isUploading)
            }

            if let uploadMessage {
                Section {
                    Text(uploadMessage)
                        .foregroundStyle(uploadMessage.hasPrefix("Archive code") ? .green : .red)
                }
            }
        }
        .navigationTitle("New card")
        .sheet(isPresented: $showingCamera) {
            CameraCaptureView(mediaType: cameraType) { capturedMedia in
                media.append(capturedMedia)
                showingCamera = false
            } onCancel: {
                showingCamera = false
            }
            .ignoresSafeArea()
        }
    }

    private func importPhotos(_ items: [PhotosPickerItem]) async {
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self) else { continue }
            let isVideo = item.supportedContentTypes.contains(where: { $0.conforms(to: .movie) })
            let fileExtension = isVideo ? "mov" : "jpg"
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent(UUID().uuidString)
                .appendingPathExtension(fileExtension)
            do {
                try data.write(to: url, options: .atomic)
                let captured = CapturedMedia(
                    fileURL: url,
                    kind: isVideo ? .video : .image,
                    fileName: url.lastPathComponent
                )
                await MainActor.run {
                    if !media.contains(captured) {
                        media.append(captured)
                    }
                }
            } catch {
                await MainActor.run {
                    uploadMessage = "Could not import one of the selected files."
                }
            }
        }
        await MainActor.run {
            selectedPhotos = []
        }
    }

    private func uploadIntake() async {
        guard let pairing = pairingStore.pairing else { return }
        isUploading = true
        uploadMessage = nil
        defer { isUploading = false }
        do {
            let client = LocalReceiverClient(pairing: pairing)
            let receipt = try await client.createIntake(note: note.isEmpty ? nil : note)
            for item in media {
                try await client.upload(item, to: receipt.intakeId)
            }
            let archive = try await client.completeIntake(receipt.intakeId)
            uploadMessage = "Archive code: \(archive.archiveCode)"
        } catch {
            uploadMessage = error.localizedDescription
        }
    }
}

struct QRScannerView: UIViewControllerRepresentable {
    let onPayload: (String) -> Void
    let onCancel: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onPayload: onPayload, onCancel: onCancel)
    }

    func makeUIViewController(context: Context) -> QRScannerController {
        QRScannerController(coordinator: context.coordinator)
    }

    func updateUIViewController(_ controller: QRScannerController, context: Context) {}

    final class Coordinator: NSObject {
        let onPayload: (String) -> Void
        let onCancel: () -> Void

        init(onPayload: @escaping (String) -> Void, onCancel: @escaping () -> Void) {
            self.onPayload = onPayload
            self.onCancel = onCancel
        }
    }
}

final class QRScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    private let coordinator: QRScannerView.Coordinator
    private let session = AVCaptureSession()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var didScan = false

    init(coordinator: QRScannerView.Coordinator) {
        self.coordinator = coordinator
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        configureScanner()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    private func configureScanner() {
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else {
            return
        }
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addInput(input)
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer)
        previewLayer = layer
        session.startRunning()
    }

    func metadataOutput(
        _ output: AVCaptureMetadataOutput,
        didOutput metadataObjects: [AVMetadataObject],
        from connection: AVCaptureConnection
    ) {
        guard !didScan,
              let readable = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let value = readable.stringValue else { return }
        didScan = true
        session.stopRunning()
        coordinator.onPayload(value)
    }
}
