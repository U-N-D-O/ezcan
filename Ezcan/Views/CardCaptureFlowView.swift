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
    @State private var cardGeneration = 0
    @State private var isCameraDismissing = false

    var body: some View {
        HStack(spacing: 0) {
            dashboardSidebar
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(background)
        .preferredColorScheme(.light)
        .task(id: cardGeneration) {
            guard !hasStarted else { return }
            hasStarted = true
            await createIntake()
        }
        .onChange(of: phase) { _, newPhase in
            if case .capturing(let stage) = newPhase, cameraStage == nil, !isBusy, !isCameraDismissing {
                cameraStage = stage
            }
        }
        .fullScreenCover(item: $cameraStage) { stage in
            GuidedCameraView(
                title: stage.title,
                mode: stage.cameraMode,
                onPhoto: { media in
                    cameraStage = nil
                    isCameraDismissing = true
                    upload(media, for: stage)
                },
                onVideo: { media in
                    cameraStage = nil
                    isCameraDismissing = true
                    upload(media, for: stage)
                },
                onBack: {
                    cameraStage = nil
                    isCameraDismissing = false
                    goBack(from: stage)
                },
                onNext: {
                    cameraStage = nil
                    isCameraDismissing = false
                    goNext(from: stage)
                },
                onCancel: {
                    cameraStage = nil
                    isCameraDismissing = false
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
        EzcanBackground()
    }

    private var dashboardSidebar: some View {
        VStack(spacing: 10) {
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: 38, height: 38)
                .padding(.bottom, 20)
            RoundedRectangle(cornerRadius: 1)
                .fill(EzcanTheme.line)
                .frame(width: 24, height: 1)
            EzcanNavigationItem(title: "Capture", icon: "camera.viewfinder", isSelected: isCaptureSection) {
                guard !isBusy else { return }
                phase = .capturing(.front)
            }
            EzcanNavigationItem(title: "Files", icon: "folder", isSelected: sharedFilesPresented) {
                sharedFilesPresented = true
            }
            Spacer()
            EzcanStatusPill(title: "LIVE")
            Button {
                pairingStore.unpair()
            } label: {
                Image(systemName: "rectangle.portrait.and.arrow.right")
                    .font(.headline)
                    .foregroundStyle(EzcanTheme.pink)
                    .frame(width: 44, height: 44)
                    .background(EzcanTheme.pinkSoft, in: Circle())
            }
            .accessibilityLabel("Disconnect computer")
        }
        .frame(width: 82)
        .padding(.vertical, 24)
        .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .shadow(color: EzcanTheme.shadow, radius: 14, y: 5)
        .padding(.leading, 12)
        .padding(.vertical, 14)
    }

    private var isCaptureSection: Bool {
        switch phase {
        case .capturing, .preparing, .options, .naming: return true
        case .complete, .failed: return false
        }
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
        GeometryReader { proxy in
            appHeader(compact: proxy.size.width < 390)
        }
        .frame(height: 62)
    }

    private func appHeader(compact: Bool) -> some View {
        HStack(spacing: compact ? 7 : 10) {
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: compact ? 32 : 38, height: compact ? 32 : 38)
            VStack(alignment: .leading, spacing: 2) {
                Text("EZCAN")
                    .font(.system(size: compact ? 14 : 15, weight: .bold, design: .rounded))
                    .tracking(compact ? 1.1 : 1.4)
                    .foregroundStyle(EzcanTheme.ink)
                Text("Card workspace")
                    .font(.caption)
                    .foregroundStyle(EzcanTheme.muted)
            }
            Spacer()
            EzcanStatusPill(title: "ONLINE")
        }
        .foregroundStyle(EzcanTheme.ink)
        .padding(.horizontal, compact ? 14 : 22)
        .padding(.top, compact ? 8 : 12)
    }

    private var preparingView: some View {
        VStack(spacing: 18) {
            Spacer()
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: 120, height: 120)
            ProgressView()
                .tint(EzcanTheme.cyan)
            Text("Preparing your card")
                .font(.headline)
                .foregroundStyle(EzcanTheme.ink)
            Text("Starting capture")
                .font(.subheadline)
                .foregroundStyle(EzcanTheme.muted)
            Spacer()
        }
    }

    private func capturePrompt(_ stage: CaptureStage) -> some View {
        VStack(spacing: 0) {
            header
            Spacer()
            VStack(spacing: 16) {
                Image(systemName: stage == .video ? "video.fill" : "camera.viewfinder")
                    .font(.system(size: 34, weight: .medium))
                    .foregroundStyle(EzcanTheme.cyan)
                Text(stage.title.uppercased())
                    .font(.system(size: 34, weight: .black, design: .rounded))
                    .tracking(2)
                    .foregroundStyle(EzcanTheme.ink)
                Text(stage == .video ? "Move slowly around the card surface" : "Place the card inside the guide")
                    .foregroundStyle(EzcanTheme.muted)
                Button {
                    cameraStage = stage
                } label: {
                    Label("Open camera", systemImage: "camera.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 17)
                }
                .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.blue))
                .disabled(isBusy)
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 28)
            .frame(maxWidth: 430)
            .ezcanPanel(accent: EzcanTheme.cyan, glow: true)
            Spacer()
            if let statusMessage {
                statusBanner(statusMessage)
            }
        }
    }

    private var optionsView: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                header
                VStack(spacing: 10) {
                    Text("CARD MEDIA")
                        .font(.system(size: 30, weight: .black, design: .rounded))
                        .tracking(1.6)
                        .foregroundStyle(EzcanTheme.ink)
                    Text("Add anything that helps show this card clearly.")
                        .font(.subheadline)
                        .foregroundStyle(EzcanTheme.muted)
                        .multilineTextAlignment(.center)
                }
                .padding(.top, 28)
                .padding(.bottom, 28)
                captureSummary
                VStack(spacing: 13) {
                    optionButton("Additional photo", "Corners, edges, holo or defects", "plus.viewfinder", EzcanTheme.amber) {
                        phase = .capturing(.additional)
                    }
                    optionButton("Surface video", "1080p HD, up to 30 seconds", "video.fill", EzcanTheme.magenta) {
                        phase = .capturing(.video)
                    }
                    optionButton("Files from computer", "Download an IPA or other shared file", "arrow.down.circle.fill", EzcanTheme.green) {
                        sharedFilesPresented = true
                    }
                    optionButton("Next", "Choose the archive code", "arrow.right.circle.fill", EzcanTheme.blue) {
                        phase = .naming
                    }
                }
                .padding(.horizontal, 22)
                .padding(.bottom, 22)
                if let statusMessage {
                    statusBanner(statusMessage)
                        .padding(.bottom, 20)
                }
            }
        }
    }

    private var captureSummary: some View {
        HStack(spacing: 0) {
            summaryMetric(value: "\(min(capturedMedia.count, 2))/2", label: "REQUIRED", color: EzcanTheme.cyan)
            Divider().frame(height: 38).overlay(EzcanTheme.line)
            summaryMetric(value: "\(max(0, capturedMedia.count - 2))", label: "OPTIONAL", color: EzcanTheme.amber)
            Divider().frame(height: 38).overlay(EzcanTheme.line)
            summaryMetric(value: "LIVE", label: "COMPUTER", color: EzcanTheme.green)
        }
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity)
        .ezcanPanel()
        .padding(.horizontal, 22)
        .padding(.bottom, 18)
    }

    private func summaryMetric(value: String, label: String, color: Color) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.system(size: 17, weight: .bold, design: .rounded))
                .foregroundStyle(color)
            Text(label)
                .font(.system(size: 9, weight: .bold, design: .rounded))
                .foregroundStyle(EzcanTheme.muted)
        }
        .frame(maxWidth: .infinity)
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
                    .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(EzcanTheme.ink)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(EzcanTheme.muted)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(EzcanTheme.muted)
            }
            .padding(16)
                .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 18)
                    .stroke(EzcanTheme.line, lineWidth: 1)
            }
                .shadow(color: EzcanTheme.shadow, radius: 10, y: 4)
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
                    .foregroundStyle(EzcanTheme.cyan)
                Text("Name this card")
                    .font(.system(size: 32, weight: .black, design: .rounded))
                    .foregroundStyle(EzcanTheme.ink)
                Text("Use the four-character archive code for this physical card.")
                    .font(.subheadline)
                    .foregroundStyle(EzcanTheme.muted)
                    .multilineTextAlignment(.center)
                TextField("A2B4", text: $archiveCode)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .keyboardType(.asciiCapable)
                    .font(.system(size: 32, weight: .bold, design: .monospaced))
                    .multilineTextAlignment(.center)
                    .padding(.vertical, 16)
                    .foregroundStyle(EzcanTheme.ink)
                    .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 14)
                            .stroke(ArchiveCodeRules.isValid(archiveCode) ? EzcanTheme.green : EzcanTheme.line, lineWidth: 2)
                    }
                    .onChange(of: archiveCode) { _, value in
                        archiveCode = ArchiveCodeRules.filtered(value)
                    }
                Text("Letter, number, letter, number")
                    .font(.caption)
                    .foregroundStyle(EzcanTheme.muted.opacity(0.75))
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
                .buttonStyle(EzcanSecondaryButtonStyle())
                Button {
                    Task { await finishCard() }
                } label: {
                    if isBusy {
                        ProgressView().tint(.white)
                    } else {
                        Label("Finish card", systemImage: "checkmark.circle.fill")
                    }
                }
                .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.blue))
                .frame(maxWidth: .infinity, minHeight: 64)
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
                .foregroundStyle(EzcanTheme.green)
                .padding(.horizontal, 25)
                .padding(.vertical, 18)
                .background(EzcanTheme.green.opacity(0.12), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            Text("The photos and video are safely on the computer.")
                .font(.subheadline)
                .foregroundStyle(EzcanTheme.muted)
                .multilineTextAlignment(.center)
            Button {
                resetForNextCard()
            } label: {
                Label("Next card", systemImage: "plus.circle.fill")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.blue))
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
                .foregroundStyle(EzcanTheme.magenta)
            Text("Could not start card")
                .font(.title2.bold())
            Text(message)
                .multilineTextAlignment(.center)
                .foregroundStyle(EzcanTheme.muted)
            Button("Try again") {
                phase = .preparing
                hasStarted = false
            }
            .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.magenta))
            .padding(.horizontal, 28)
            Spacer()
        }
        .padding(28)
    }

    private func statusBanner(_ message: String) -> some View {
        Label(message, systemImage: message.contains("failed") ? "exclamationmark.triangle" : "arrow.up.circle")
            .font(.caption.weight(.medium))
            .foregroundStyle(message.contains("failed") ? EzcanTheme.pink : EzcanTheme.cyan)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(EzcanTheme.white, in: Capsule())
            .overlay { Capsule().stroke(EzcanTheme.line, lineWidth: 1) }
            .shadow(color: EzcanTheme.shadow, radius: 8, y: 4)
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
                    moveToNextPhase(after: stage)
                }
            } catch {
                await MainActor.run {
                    isBusy = false
                    statusMessage = "Upload failed: \(error.localizedDescription)"
                    reopenCamera(after: .capturing(stage), stage: stage)
                }
            }
        }
    }

    private func moveToNextPhase(after stage: CaptureStage) {
        let next = nextPhase(after: stage)
        phase = next
        guard case .capturing(let nextStage) = next else {
            isCameraDismissing = false
            return
        }
        reopenCamera(after: next, stage: nextStage)
    }

    private func reopenCamera(after nextPhase: CapturePhase, stage: CaptureStage) {
        phase = nextPhase
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 450_000_000)
            guard case .capturing = phase, !isBusy else { return }
            isCameraDismissing = false
            cameraStage = stage
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
        isCameraDismissing = false
        cardGeneration += 1
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
