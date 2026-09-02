import SwiftUI

enum CaptureStage: String, Identifiable, Equatable {
    case front
    case back
    case additional
    case video

    var id: String { rawValue }

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

private enum CapturePhase: Equatable {
    case preparing
    case capturing(CaptureStage)
    case options
    case naming
    case complete(String)
    case failed(String)
}

struct CardCaptureFlowView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @State private var intakeID: String?
    @State private var archiveCode = ""
    @State private var phase: CapturePhase = .preparing
    @State private var cameraStage: CaptureStage?
    @State private var capturedMedia: [CapturedMedia] = []
    @State private var nameCounts: [String: Int] = [:]
    @State private var isBusy = false
    @State private var statusMessage: String?
    @State private var sharedFilesPresented = false
    @State private var hasStarted = false

    var body: some View {
        ZStack {
            background
            content
        }
        .preferredColorScheme(.dark)
        .task {
            guard !hasStarted else { return }
            hasStarted = true
            await createIntake()
        }
        .onChange(of: phase) { _, newPhase in
            if case .capturing(let stage) = newPhase, cameraStage == nil, !isBusy {
                cameraStage = stage
            }
        }
        .fullScreenCover(item: $cameraStage) { stage in
            GuidedCameraView(
                title: stage.title,
                mode: stage.cameraMode,
                onPhoto: { media in
                    cameraStage = nil
                    upload(media, for: stage)
                },
                onVideo: { media in
                    cameraStage = nil
                    upload(media, for: stage)
                },
                onBack: {
                    cameraStage = nil
                    goBack(from: stage)
                },
                onNext: {
                    cameraStage = nil
                    goNext(from: stage)
                },
                onCancel: {
                    cameraStage = nil
                    phase = stage == .front || stage == .back ? .options : .options
                }
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $sharedFilesPresented) {
            SharedFilesView()
        }
    }

    private var background: some View {
        LinearGradient(
            colors: [Color(red: 0.04, green: 0.07, blue: 0.14), Color(red: 0.02, green: 0.03, blue: 0.06)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .ignoresSafeArea()
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .preparing:
            preparingView
        case .capturing(let stage):
            capturePrompt(stage)
        case .options:
            optionsView
        case .naming:
            namingView
        case .complete(let code):
            completedView(code)
        case .failed(let message):
            failedView(message)
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
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
                sharedFilesPresented = true
            } label: {
                Image(systemName: "arrow.down.circle")
                    .font(.headline)
                    .padding(10)
                    .background(.white.opacity(0.1), in: Circle())
            }
            .accessibilityLabel("Files from computer")
            Button {
                pairingStore.unpair()
            } label: {
                Image(systemName: "rectangle.portrait.and.arrow.right")
                    .font(.headline)
                    .padding(10)
                    .background(.white.opacity(0.1), in: Circle())
            }
            .accessibilityLabel("Disconnect computer")
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 22)
        .padding(.top, 12)
    }

    private var preparingView: some View {
        VStack(spacing: 18) {
            Spacer()
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
            Spacer()
        }
    }

    private func capturePrompt(_ stage: CaptureStage) -> some View {
        VStack(spacing: 0) {
            header
            Spacer()
            VStack(spacing: 16) {
                Text(stage.title.uppercased())
                    .font(.system(size: 34, weight: .black, design: .rounded))
                    .tracking(2)
                Text(stage == .video ? "Move slowly around the card surface" : "Place the card inside the guide")
                    .foregroundStyle(.white.opacity(0.7))
                Button {
                    cameraStage = stage
                } label: {
                    Label("Open camera", systemImage: "camera.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 17)
                }
                .buttonStyle(PrimaryActionButtonStyle())
                .disabled(isBusy)
            }
            .padding(.horizontal, 28)
            Spacer()
            if let statusMessage {
                statusBanner(statusMessage)
            }
        }
    }

    private var optionsView: some View {
        VStack(spacing: 0) {
            header
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
                optionButton("Additional photo", "Corners, edges, holo or defects", "plus.viewfinder", .orange) {
                    phase = .capturing(.additional)
                }
                optionButton("Surface video", "1080p HD, up to 30 seconds", "video.fill", .red) {
                    phase = .capturing(.video)
                }
                optionButton("Files from computer", "Download an IPA or other shared file", "arrow.down.circle.fill", .green) {
                    sharedFilesPresented = true
                }
                optionButton("Next", "Choose the archive code", "arrow.right.circle.fill", .blue) {
                    phase = .naming
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
        _ title: String,
        _ detail: String,
        _ icon: String,
        _ tint: Color,
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
            header
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
                    .onChange(of: archiveCode) { _, value in
                        archiveCode = ArchiveCodeRules.filtered(value)
                    }
                Text("Letter, number, letter, number")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.48))
            }
            .padding(.horizontal, 32)
            Spacer()
            HStack(spacing: 12) {
                Button {
                    phase = .options
                } label: {
                    Image(systemName: "chevron.left")
                        .frame(width: 56, height: 56)
                }
                .buttonStyle(SecondaryActionButtonStyle())
                Button {
                    Task { await finishCard() }
                } label: {
                    if isBusy {
                        ProgressView().tint(.white)
                    } else {
                        Label("Finish card", systemImage: "checkmark.circle.fill")
                    }
                }
                .buttonStyle(PrimaryActionButtonStyle())
                .disabled(!ArchiveCodeRules.isValid(archiveCode) || isBusy)
            }
            .padding(.horizontal, 22)
            .padding(.bottom, 24)
        }
    }

    private func completedView(_ code: String) -> some View {
        VStack(spacing: 22) {
            Spacer()
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
            Spacer()
        }
        .padding(28)
    }

    private func failedView(_ message: String) -> some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48))
                .foregroundStyle(.orange)
            Text("Could not start card")
                .font(.title2.bold())
            Text(message)
                .multilineTextAlignment(.center)
                .foregroundStyle(.white.opacity(0.7))
            Button("Try again") {
                phase = .preparing
                hasStarted = false
            }
            .buttonStyle(PrimaryActionButtonStyle())
            .padding(.horizontal, 28)
            Spacer()
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

    private func createIntake() async {
        guard let pairing = pairingStore.pairing else { return }
        do {
            let receipt = try await LocalReceiverClient(pairing: pairing).createIntake(note: nil)
            await MainActor.run {
                intakeID = receipt.intakeId
                archiveCode = receipt.suggestedArchiveCode ?? ArchiveCodeRules.suggested()
                phase = .capturing(.front)
            }
        } catch {
            await MainActor.run {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    private func upload(_ media: CapturedMedia, for stage: CaptureStage) {
        guard let intakeID, let pairing = pairingStore.pairing else { return }
        let namedMedia = media.named(nextFileName(for: stage, original: media.fileName))
        capturedMedia.append(namedMedia)
        isBusy = true
        statusMessage = "Sending \(namedMedia.fileName)..."
        Task {
            do {
                try await LocalReceiverClient(pairing: pairing).upload(namedMedia, to: intakeID)
                await MainActor.run {
                    isBusy = false
                    statusMessage = "Sent \(namedMedia.fileName)"
                    phase = nextPhase(after: stage)
                }
            } catch {
                await MainActor.run {
                    isBusy = false
                    statusMessage = "Upload failed: \(error.localizedDescription)"
                    phase = .capturing(stage)
                }
            }
        }
    }

    private func nextPhase(after stage: CaptureStage) -> CapturePhase {
        switch stage {
        case .front: return .capturing(.back)
        case .back, .additional, .video: return .options
        }
    }

    private func nextFileName(for stage: CaptureStage, original: String) -> String {
        let base = stage.rawValue
        let originalExtension = (original as NSString).pathExtension
        let fileExtension = originalExtension.isEmpty ? (stage == .video ? "mov" : "jpg") : originalExtension
        let count = (nameCounts[base] ?? 0) + 1
        nameCounts[base] = count
        return "\(base)\(count == 1 ? "" : String(count)).\(fileExtension)"
    }

    private func goBack(from stage: CaptureStage) {
        switch stage {
        case .front: phase = .options
        case .back: phase = .capturing(.front)
        case .additional, .video: phase = .options
        }
    }

    private func goNext(from stage: CaptureStage) {
        switch stage {
        case .front: phase = .capturing(.back)
        case .back, .additional, .video: phase = .options
        }
    }

    private func finishCard() async {
        guard let intakeID, let pairing = pairingStore.pairing else { return }
        isBusy = true
        do {
            let receipt = try await LocalReceiverClient(pairing: pairing).completeIntake(intakeID, archiveCode: archiveCode)
            await MainActor.run {
                isBusy = false
                phase = .complete(receipt.archiveCode)
            }
        } catch {
            await MainActor.run {
                isBusy = false
                statusMessage = "Upload failed: \(error.localizedDescription)"
            }
        }
    }

    private func resetForNextCard() {
        intakeID = nil
        archiveCode = ""
        phase = .preparing
        cameraStage = nil
        capturedMedia = []
        nameCounts = [:]
        isBusy = false
        statusMessage = nil
        hasStarted = false
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