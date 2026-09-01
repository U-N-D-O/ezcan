import AVFoundation
import SwiftUI
import UIKit

struct ContentView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @State private var requiresLaunchPairing = true

    var body: some View {
        Group {
            if pairingStore.isPaired && !requiresLaunchPairing {
                CardCaptureFlowView()
            } else {
                PairingView {
                    requiresLaunchPairing = false
                }
            }
        }
    }
}

struct PairingView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    let onPaired: () -> Void
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
            .onAppear {
                showingScanner = true
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
            onPaired()
        } catch {
            pairingStore.errorMessage = error.localizedDescription
        }
    }

    private func pairFromPayload() {
        do {
            pairingStore.pair(with: try PairingCode.decode(qrPayload))
            onPaired()
        } catch {
            pairingStore.errorMessage = error.localizedDescription
        }
    }
}

enum CaptureStage: Equatable {
    case front
    case back
    case additional
    case video
}

extension CaptureStage {
    var title: String {
        switch self {
        case .front: return "Front"
        case .back: return "Back"
        case .additional: return "Additional"
        case .video: return "Video"
        }
    }

    var cameraMode: GuidedCameraView.Mode {
        self == .video ? .video : .photo
    }
}

struct CardCaptureFlowView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @State private var intakeID: String?
    @State private var archiveCode = ""
    @State private var stage: CaptureStage?
    @State private var activeCameraStage: CaptureStage?
    @State private var showingNaming = false
    @State private var isPreparing = true
    @State private var isSending = false
    @State private var capturedMedia: [CapturedMedia] = []
    @State private var nameCounters: [String: Int] = [:]
    @State private var statusMessage: String?
    @State private var completedCode: String?
    @State private var hasLoaded = false
    @State private var showingSharedFiles = false

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.04, green: 0.07, blue: 0.14), Color(red: 0.02, green: 0.03, blue: 0.06)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            if let completedCode {
                completedView(code: completedCode)
            } else if isPreparing {
                preparingView
            } else if showingNaming {
                namingView
            } else if let stage {
                flowView(for: stage)
            } else {
                optionMenu
            }
        }
        .preferredColorScheme(.dark)
        .task {
            guard !hasLoaded else { return }
            hasLoaded = true
            await prepareIntake()
        }
        .fullScreenCover(isPresented: cameraPresentation) {
            if let cameraStage = activeCameraStage {
                GuidedCameraView(
                    title: cameraStage.title,
                    mode: cameraStage.cameraMode,
                    onPhoto: { media in
                        activeCameraStage = nil
                        accept(media, for: cameraStage)
                    },
                    onVideo: { media in
                        activeCameraStage = nil
                        accept(media, for: cameraStage)
                    },
                    onBack: {
                        activeCameraStage = nil
                        moveBack(from: cameraStage)
                    },
                    onNext: {
                        activeCameraStage = nil
                        advanceWithoutCapture(from: cameraStage)
                    },
                    onCancel: {
                        activeCameraStage = nil
                        stage = nil
                    }
                )
                .ignoresSafeArea()
            }
        }
        .sheet(isPresented: $showingSharedFiles) {
            SharedFilesView()
        }
    }

    private var cameraPresentation: Binding<Bool> {
        Binding(
            get: { activeCameraStage != nil },
            set: { isPresented in
                if !isPresented {
                    activeCameraStage = nil
                }
            }
        )
    }

    private var preparingView: some View {
        VStack(spacing: 18) {
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: 120, height: 120)
            ProgressView()
                .tint(.white)
            Text("Preparing your card")
                .font(.headline)
            Text("The front camera will open automatically.")
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.65))
        }
        .padding(30)
    }

    private func flowView(for currentStage: CaptureStage) -> some View {
        VStack(spacing: 0) {
            flowHeader
            Spacer()
            VStack(spacing: 16) {
                Text(currentStage.title.uppercased())
                    .font(.system(size: 34, weight: .black, design: .rounded))
                    .tracking(2)
                Text(currentStage == .front ? "Place the front inside the guide" : "Place the back inside the guide")
                    .foregroundStyle(.white.opacity(0.7))
                Button {
                    launchCamera(currentStage)
                } label: {
                    Label("Open camera", systemImage: "camera.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 17)
                }
                .buttonStyle(PrimaryActionButtonStyle())
                .disabled(isSending)
            }
            .padding(.horizontal, 28)
            Spacer()
            if let statusMessage {
                statusBanner(statusMessage)
            }
        }
        .padding(.top, 12)
        .onAppear {
            if activeCameraStage == nil && !isSending {
                launchCamera(currentStage)
            }
        }
    }

    private var flowHeader: some View {
        HStack {
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: 38, height: 38)
            VStack(alignment: .leading, spacing: 2) {
                Text("EZCAN")
                    .font(.system(size: 15, weight: .black, design: .rounded))
                    .tracking(1.4)
                Text("Card capture")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.6))
            }
            Spacer()
            Button {
                showingSharedFiles = true
            } label: {
                Image(systemName: "arrow.down.circle")
                    .font(.headline)
                    .foregroundStyle(.white.opacity(0.8))
                    .padding(10)
                    .background(.white.opacity(0.1), in: Circle())
            }
            .accessibilityLabel("Files from computer")
            Button {
                pairingStore.unpair()
            } label: {
                Image(systemName: "rectangle.portrait.and.arrow.right")
                    .font(.headline)
                    .foregroundStyle(.white.opacity(0.8))
                    .padding(10)
                    .background(.white.opacity(0.1), in: Circle())
            }
            .accessibilityLabel("Disconnect computer")
        }
        .padding(.horizontal, 22)
    }

    private var optionMenu: some View {
        VStack(spacing: 0) {
            flowHeader
            VStack(spacing: 10) {
                Text("CARD MEDIA")
                    .font(.system(size: 30, weight: .black, design: .rounded))
                    .tracking(1.6)
                Text("Add anything that helps show this card clearly.")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.66))
                    .multilineTextAlignment(.center)
            }
            .padding(.top, 42)
            Spacer()
            VStack(spacing: 13) {
                optionButton(title: "Additional photo", detail: "Corners, edges, holo or defects", icon: "plus.viewfinder", tint: .orange) {
                    launchCamera(.additional)
                }
                optionButton(title: "Surface video", detail: "1080p HD • up to 30 seconds", icon: "video.fill", tint: .red) {
                    launchCamera(.video)
                }
                optionButton(title: "Files from computer", detail: "Download an IPA or other shared file", icon: "arrow.down.circle.fill", tint: .green) {
                    showingSharedFiles = true
                }
                optionButton(title: "Next", detail: "Choose the archive code", icon: "arrow.right.circle.fill", tint: .blue) {
                    showingNaming = true
                    stage = nil
                }
            }
            .padding(.horizontal, 22)
            Spacer()
            if let statusMessage {
                statusBanner(statusMessage)
                    .padding(.bottom, 20)
            }
        }
    }

    private func optionButton(
        title: String,
        detail: String,
        icon: String,
        tint: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 16) {
                Image(systemName: icon)
                    .font(.title2.weight(.bold))
                    .foregroundStyle(tint)
                    .frame(width: 46, height: 46)
                    .background(tint.opacity(0.14), in: RoundedRectangle(cornerRadius: 14))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.white.opacity(0.6))
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(.white.opacity(0.45))
            }
            .padding(16)
            .background(.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 18))
            .overlay {
                RoundedRectangle(cornerRadius: 18)
                    .stroke(.white.opacity(0.1), lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
    }

    private var namingView: some View {
        VStack(spacing: 0) {
            flowHeader
            Spacer()
            VStack(spacing: 20) {
                Image(systemName: "barcode.viewfinder")
                    .font(.system(size: 50, weight: .medium))
                    .foregroundStyle(.blue)
                Text("Name this card")
                    .font(.system(size: 32, weight: .black, design: .rounded))
                Text("Use the four-character archive code for this physical card.")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.65))
                    .multilineTextAlignment(.center)
                TextField("A2B4", text: $archiveCode)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .keyboardType(.asciiCapable)
                    .font(.system(size: 32, weight: .bold, design: .monospaced))
                    .multilineTextAlignment(.center)
                    .padding(.vertical, 16)
                    .background(.white.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
                    .overlay {
                        RoundedRectangle(cornerRadius: 14)
                            .stroke(ArchiveCodeRules.isValid(archiveCode) ? .green : .white.opacity(0.18), lineWidth: 2)
                    }
                    .onChange(of: archiveCode) { _, newValue in
                        archiveCode = ArchiveCodeRules.filtered(newValue)
                    }
                Text("Letter • number • letter • number")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.48))
            }
            .padding(.horizontal, 32)
            Spacer()
            HStack(spacing: 12) {
                Button {
                    showingNaming = false
                    stage = nil
                } label: {
                    Image(systemName: "chevron.left")
                        .frame(width: 56, height: 56)
                }
                .buttonStyle(SecondaryActionButtonStyle())
                Button {
                    Task { await finishCard() }
                } label: {
                    if isSending {
                        ProgressView().tint(.white)
                    } else {
                        Label("Finish card", systemImage: "checkmark.circle.fill")
                    }
                }
                .buttonStyle(PrimaryActionButtonStyle())
                .disabled(!ArchiveCodeRules.isValid(archiveCode) || isSending)
            }
            .padding(.horizontal, 22)
            .padding(.bottom, 24)
        }
    }

    private func completedView(code: String) -> some View {
        VStack(spacing: 22) {
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: 110, height: 110)
            Text("CARD ARCHIVED")
                .font(.system(size: 26, weight: .black, design: .rounded))
                .tracking(1.2)
            Text(code)
                .font(.system(size: 58, weight: .bold, design: .monospaced))
                .foregroundStyle(.green)
                .padding(.horizontal, 25)
                .padding(.vertical, 18)
                .background(.green.opacity(0.12), in: RoundedRectangle(cornerRadius: 18))
            Text("The photos and video are safely on the computer.")
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.65))
                .multilineTextAlignment(.center)
            Button {
                resetForNextCard()
            } label: {
                Label("Next card", systemImage: "plus.circle.fill")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(PrimaryActionButtonStyle())
            .padding(.horizontal, 28)
        }
        .padding(28)
    }

    private func statusBanner(_ message: String) -> some View {
        Label(message, systemImage: message.contains("failed") ? "exclamationmark.triangle" : "arrow.up.circle")
            .font(.caption.weight(.medium))
            .foregroundStyle(message.contains("failed") ? .orange : .white.opacity(0.72))
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(.black.opacity(0.28), in: Capsule())
    }

    private func prepareIntake() async {
        guard let pairing = pairingStore.pairing else { return }
        do {
            let receipt = try await LocalReceiverClient(pairing: pairing).createIntake(note: nil)
            await MainActor.run {
                intakeID = receipt.intakeId
                archiveCode = receipt.suggestedArchiveCode ?? ArchiveCodeRules.suggested()
                stage = .front
                isPreparing = false
            }
        } catch {
            await MainActor.run {
                statusMessage = "Upload failed: \(error.localizedDescription)"
                isPreparing = false
                stage = .front
            }
        }
    }

    private func launchCamera(_ cameraStage: CaptureStage) {
        guard !isSending else { return }
        stage = cameraStage
        activeCameraStage = cameraStage
    }

    private func accept(_ media: CapturedMedia, for captureStage: CaptureStage) {
        let fileName = nextFileName(for: captureStage, original: media.fileName)
        let namedMedia = media.named(fileName)
        capturedMedia.append(namedMedia)
        isSending = true
        statusMessage = "Sending \(fileName)..."
        Task {
            do {
                guard let intakeID, let pairing = pairingStore.pairing else { return }
                try await LocalReceiverClient(pairing: pairing).upload(namedMedia, to: intakeID)
                await MainActor.run {
                    isSending = false
                    statusMessage = "Sent \(fileName)"
                    switch captureStage {
                    case .front:
                        stage = .back
                        activeCameraStage = .back
                    case .back:
                        stage = nil
                    case .additional, .video:
                        stage = nil
                    }
                }
            } catch {
                await MainActor.run {
                    isSending = false
                    statusMessage = "Upload failed: \(error.localizedDescription)"
                    activeCameraStage = captureStage
                    stage = captureStage
                }
            }
        }
    }

    private func nextFileName(for captureStage: CaptureStage, original: String) -> String {
        let base: String
        let fileExtension = (original as NSString).pathExtension.isEmpty ? (captureStage == .video ? "mov" : "jpg") : (original as NSString).pathExtension
        switch captureStage {
        case .front: base = "front"
        case .back: base = "back"
        case .additional: base = "additional"
        case .video: base = "video"
        }
        let count = (nameCounters[base] ?? 0) + 1
        nameCounters[base] = count
        return "\(base)\(count == 1 ? "" : String(count)).\(fileExtension)"
    }

    private func moveBack(from captureStage: CaptureStage) {
        switch captureStage {
        case .front:
            activeCameraStage = nil
        case .back:
            stage = .front
            activeCameraStage = .front
        case .additional, .video:
            stage = nil
            activeCameraStage = nil
        }
    }

    private func advanceWithoutCapture(from captureStage: CaptureStage) {
        switch captureStage {
        case .front:
            stage = .back
            activeCameraStage = .back
        case .back, .additional, .video:
            stage = nil
        }
    }

    private func finishCard() async {
        guard let intakeID, let pairing = pairingStore.pairing else { return }
        isSending = true
        do {
            let archive = try await LocalReceiverClient(pairing: pairing).completeIntake(intakeID, archiveCode: archiveCode)
            await MainActor.run {
                completedCode = archive.archiveCode
                isSending = false
            }
        } catch {
            await MainActor.run {
                isSending = false
                statusMessage = "Upload failed: \(error.localizedDescription)"
            }
        }
    }

    private func resetForNextCard() {
        intakeID = nil
        archiveCode = ""
        stage = nil
        activeCameraStage = nil
        showingNaming = false
        isPreparing = true
        isSending = false
        capturedMedia = []
        nameCounters = [:]
        statusMessage = nil
        completedCode = nil
        Task { await prepareIntake() }
    }
}

private enum ArchiveCodeRules {
    static let letters = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    static let digits = Array("0123456789")

    static func filtered(_ value: String) -> String {
        var result = ""
        for character in value.uppercased() where result.count < 4 {
            let index = result.count
            if index.isMultiple(of: 2) {
                if letters.contains(character) { result.append(character) }
            } else if digits.contains(character) {
                result.append(character)
            }
        }
        return result
    }

    static func isValid(_ value: String) -> Bool {
        let characters = Array(value)
        return characters.count == 4
            && letters.contains(characters[0])
            && digits.contains(characters[1])
            && letters.contains(characters[2])
            && digits.contains(characters[3])
    }

    static func suggested() -> String {
        let first = letters.randomElement() ?? "A"
        var second = letters.randomElement() ?? "B"
        while second == first { second = letters.randomElement() ?? "B" }
        return "\(first)\(digits.randomElement() ?? "2")\(second)\(digits.randomElement() ?? "3")"
    }
}

private struct PrimaryActionButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .background(
                LinearGradient(colors: [.blue, Color(red: 0.12, green: 0.35, blue: 0.9)], startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: 16)
            )
            .opacity(configuration.isPressed ? 0.78 : 1)
    }
}

private struct SecondaryActionButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .background(.white.opacity(configuration.isPressed ? 0.18 : 0.1), in: RoundedRectangle(cornerRadius: 16))
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
        requestCameraAccess()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    private func requestCameraAccess() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureScanner()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    if granted {
                        self?.configureScanner()
                    } else {
                        self?.showCameraAccessMessage()
                    }
                }
            }
        default:
            showCameraAccessMessage()
        }
    }

    private func showCameraAccessMessage() {
        let label = UILabel()
        label.text = "Camera access is required in Settings"
        label.textColor = .white
        label.textAlignment = .center
        label.numberOfLines = 0
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
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
                                Text(Self.byteCount(file.size))
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
                            .tint(.blue)
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
                let url = try await LocalReceiverClient(pairing: pairing).downloadSharedFile(file)
                shareItem = ShareItem(url: url)
            } catch {
                errorMessage = error.localizedDescription
            }
            downloadingID = nil
        }
    }

    private static func byteCount(_ size: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)
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
