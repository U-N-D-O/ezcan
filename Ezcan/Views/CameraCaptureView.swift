import AVFoundation
import SwiftUI
import UIKit

struct GuidedCameraView: UIViewControllerRepresentable {
    enum Mode {
        case photo
        case video
    }

    let title: String
    let mode: Mode
    let onPhoto: (CapturedMedia) -> Void
    let onVideo: (CapturedMedia) -> Void
    let onBack: () -> Void
    let onNext: () -> Void
    let onCancel: () -> Void

    func makeUIViewController(context: Context) -> GuidedCameraController {
        GuidedCameraController(
            title: title,
            mode: mode,
            onPhoto: onPhoto,
            onVideo: onVideo,
            onBack: onBack,
            onNext: onNext,
            onCancel: onCancel
        )
    }

    func updateUIViewController(_ controller: GuidedCameraController, context: Context) {}
}

final class GuidedCameraController: UIViewController, AVCapturePhotoCaptureDelegate, AVCaptureFileOutputRecordingDelegate {
    private let titleText: String
    private let mode: GuidedCameraView.Mode
    private let onPhoto: (CapturedMedia) -> Void
    private let onVideo: (CapturedMedia) -> Void
    private let onBack: () -> Void
    private let onNext: () -> Void
    private let onCancel: () -> Void

    private let session = AVCaptureSession()
    private let photoOutput = AVCapturePhotoOutput()
    private let movieOutput = AVCaptureMovieFileOutput()
    private let previewView = UIView()
    private let guideView = CardGuideView()
    private let timerLabel = UILabel()
    private let statusLabel = UILabel()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var recordingTimer: Timer?
    private var recordingStartedAt: Date?
    private var isRecording = false
    private var hasFinished = false

    init(
        title: String,
        mode: GuidedCameraView.Mode,
        onPhoto: @escaping (CapturedMedia) -> Void,
        onVideo: @escaping (CapturedMedia) -> Void,
        onBack: @escaping () -> Void,
        onNext: @escaping () -> Void,
        onCancel: @escaping () -> Void
    ) {
        self.titleText = title
        self.mode = mode
        self.onPhoto = onPhoto
        self.onVideo = onVideo
        self.onBack = onBack
        self.onNext = onNext
        self.onCancel = onCancel
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.03, green: 0.05, blue: 0.08, alpha: 1)
        configureView()
        requestCameraAccess()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = previewView.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        recordingTimer?.invalidate()
        if session.isRunning {
            session.stopRunning()
        }
    }

    private func configureView() {
        previewView.translatesAutoresizingMaskIntoConstraints = false
        previewView.backgroundColor = .black
        view.addSubview(previewView)
        NSLayoutConstraint.activate([
            previewView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            previewView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            previewView.topAnchor.constraint(equalTo: view.topAnchor),
            previewView.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])

        let shade = UIView()
        shade.translatesAutoresizingMaskIntoConstraints = false
        shade.backgroundColor = UIColor.black.withAlphaComponent(0.18)
        shade.isUserInteractionEnabled = false
        view.addSubview(shade)
        NSLayoutConstraint.activate([
            shade.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            shade.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            shade.topAnchor.constraint(equalTo: view.topAnchor),
            shade.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])

        guideView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(guideView)
        NSLayoutConstraint.activate([
            guideView.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            guideView.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -18),
            guideView.widthAnchor.constraint(equalTo: view.widthAnchor, multiplier: 0.76),
            guideView.heightAnchor.constraint(equalTo: guideView.widthAnchor, multiplier: 1.4)
        ])

        let titleLabel = UILabel()
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        titleLabel.text = titleText.uppercased()
        titleLabel.textColor = .white
        titleLabel.font = .systemFont(ofSize: 27, weight: .bold)
        titleLabel.textAlignment = .center
        view.addSubview(titleLabel)

        let subtitleLabel = UILabel()
        subtitleLabel.translatesAutoresizingMaskIntoConstraints = false
        subtitleLabel.text = mode == .photo ? "Fit the whole card inside the corners" : "Move slowly around the card surface"
        subtitleLabel.textColor = UIColor.white.withAlphaComponent(0.82)
        subtitleLabel.font = .systemFont(ofSize: 14, weight: .medium)
        subtitleLabel.textAlignment = .center
        view.addSubview(subtitleLabel)

        timerLabel.translatesAutoresizingMaskIntoConstraints = false
        timerLabel.text = "00:00"
        timerLabel.textColor = .white
        timerLabel.font = UIFont.monospacedDigitSystemFont(ofSize: 17, weight: .semibold)
        timerLabel.textAlignment = .center
        timerLabel.isHidden = mode == .photo
        view.addSubview(timerLabel)

        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.text = "Preparing camera..."
        statusLabel.textColor = UIColor.white.withAlphaComponent(0.8)
        statusLabel.font = .systemFont(ofSize: 13, weight: .regular)
        statusLabel.textAlignment = .center
        view.addSubview(statusLabel)

        let backButton = makeButton(title: "Back", imageName: "chevron.left")
        backButton.addAction(UIAction { [weak self] _ in self?.handleBack() }, for: .touchUpInside)
        view.addSubview(backButton)

        let cancelButton = makeButton(title: "Cancel", imageName: "xmark")
        cancelButton.addAction(UIAction { [weak self] _ in self?.handleCancel() }, for: .touchUpInside)
        view.addSubview(cancelButton)

        let nextButton = makeButton(title: "Next", imageName: "chevron.right")
        nextButton.isHidden = mode == .video
        nextButton.addAction(UIAction { [weak self] _ in self?.handleNext() }, for: .touchUpInside)
        view.addSubview(nextButton)

        let captureButton = UIButton(type: .custom)
        captureButton.translatesAutoresizingMaskIntoConstraints = false
        captureButton.backgroundColor = .white
        captureButton.layer.cornerRadius = 38
        captureButton.layer.borderWidth = 5
        captureButton.layer.borderColor = UIColor.white.withAlphaComponent(0.35).cgColor
        captureButton.addAction(UIAction { [weak self] _ in self?.captureButtonPressed(captureButton) }, for: .touchUpInside)
        view.addSubview(captureButton)

        let bottomHint = UILabel()
        bottomHint.translatesAutoresizingMaskIntoConstraints = false
        bottomHint.text = mode == .photo ? "Photo will be cropped with an approx. 1 cm border" : "1080p HD video • up to 30 seconds"
        bottomHint.textColor = UIColor.white.withAlphaComponent(0.75)
        bottomHint.font = .systemFont(ofSize: 12, weight: .medium)
        bottomHint.textAlignment = .center
        view.addSubview(bottomHint)

        NSLayoutConstraint.activate([
            titleLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 18),
            titleLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            subtitleLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 5),
            subtitleLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            timerLabel.topAnchor.constraint(equalTo: subtitleLabel.bottomAnchor, constant: 8),
            timerLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            statusLabel.topAnchor.constraint(equalTo: guideView.bottomAnchor, constant: 14),
            statusLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            statusLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            backButton.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 18),
            backButton.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            cancelButton.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -18),
            cancelButton.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            nextButton.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -18),
            nextButton.topAnchor.constraint(equalTo: cancelButton.bottomAnchor, constant: 10),
            captureButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            captureButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -50),
            captureButton.widthAnchor.constraint(equalToConstant: 76),
            captureButton.heightAnchor.constraint(equalToConstant: 76),
            bottomHint.topAnchor.constraint(equalTo: captureButton.bottomAnchor, constant: 12),
            bottomHint.centerXAnchor.constraint(equalTo: view.centerXAnchor)
        ])
    }

    private func makeButton(title: String, imageName: String) -> UIButton {
        var configuration = UIButton.Configuration.plain()
        configuration.title = title
        configuration.image = UIImage(systemName: imageName)
        configuration.imagePadding = 5
        configuration.baseForegroundColor = .white
        configuration.titleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { attributes in
            var updated = attributes
            updated.font = .systemFont(ofSize: 15, weight: .semibold)
            return updated
        }
        let button = UIButton(configuration: configuration)
        button.translatesAutoresizingMaskIntoConstraints = false
        return button
    }

    private func requestCameraAccess() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureSession()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    if granted {
                        self?.configureSession()
                    } else {
                        self?.statusLabel.text = "Camera access is required in Settings"
                    }
                }
            }
        default:
            statusLabel.text = "Camera access is required in Settings"
        }
    }

    private func configureSession() {
        session.beginConfiguration()
        session.sessionPreset = mode == .photo ? .photo : .hd1920x1080
        defer { session.commitConfiguration() }

        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let videoInput = try? AVCaptureDeviceInput(device: camera),
              session.canAddInput(videoInput) else {
            statusLabel.text = "No camera is available"
            return
        }
        session.addInput(videoInput)

        if mode == .photo {
            guard session.canAddOutput(photoOutput) else { return }
            session.addOutput(photoOutput)
            photoOutput.isHighResolutionCaptureEnabled = true
        } else {
            guard session.canAddOutput(movieOutput) else { return }
            session.addOutput(movieOutput)
            if let microphone = AVCaptureDevice.default(for: .audio),
               let audioInput = try? AVCaptureDeviceInput(device: microphone),
               session.canAddInput(audioInput) {
                session.addInput(audioInput)
            }
        }

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        previewView.layer.addSublayer(layer)
        previewLayer = layer
        setPortraitOrientation()
        statusLabel.text = "Ready"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.session.startRunning()
        }
    }

    private func setPortraitOrientation() {
        if let connection = previewLayer?.connection, connection.isVideoOrientationSupported {
            connection.videoOrientation = .portrait
        }
    }

    private func captureButtonPressed(_ button: UIButton) {
        if mode == .photo {
            capturePhoto()
        } else if isRecording {
            stopRecording(button)
        } else {
            startRecording(button)
        }
    }

    private func capturePhoto() {
        guard !hasFinished else { return }
        let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
        settings.isHighResolutionPhotoEnabled = true
        photoOutput.capturePhoto(with: settings, delegate: self)
        statusLabel.text = "Capturing..."
    }

    private func startRecording(_ button: UIButton) {
        guard !hasFinished else { return }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("mov")
        if let connection = movieOutput.connection(with: .video), connection.isVideoOrientationSupported {
            connection.videoOrientation = .portrait
        }
        movieOutput.startRecording(to: url, recordingDelegate: self)
        isRecording = true
        recordingStartedAt = Date()
        timerLabel.text = "00:00"
        statusLabel.text = "Recording"
        button.backgroundColor = .systemRed
        recordingTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self, weak button] _ in
            guard let self, let started = self.recordingStartedAt else { return }
            let elapsed = Date().timeIntervalSince(started)
            self.timerLabel.text = Self.format(seconds: elapsed)
            if elapsed >= 30 {
                self.stopRecording(button)
            }
        }
    }

    private func stopRecording(_ button: UIButton?) {
        guard isRecording else { return }
        movieOutput.stopRecording()
        isRecording = false
        recordingTimer?.invalidate()
        recordingTimer = nil
        statusLabel.text = "Saving video..."
        button?.backgroundColor = .white
    }

    private func handleBack() {
        guard !isRecording else { return }
        hasFinished = true
        onBack()
    }

    private func handleNext() {
        guard !isRecording else { return }
        hasFinished = true
        onNext()
    }

    private func handleCancel() {
        guard !isRecording else { return }
        hasFinished = true
        onCancel()
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        guard error == nil,
              let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data),
              let croppedData = cropCard(image: image),
              let url = save(data: croppedData, extension: "jpg") else {
            statusLabel.text = "Could not capture photo"
            return
        }
        hasFinished = true
        session.stopRunning()
        onPhoto(CapturedMedia(fileURL: url, kind: .image, fileName: url.lastPathComponent))
    }

    func fileOutput(
        _ output: AVCaptureFileOutput,
        didFinishRecordingTo outputFileURL: URL,
        from connections: [AVCaptureConnection],
        error: Error?
    ) {
        guard error == nil else {
            statusLabel.text = "Could not save video"
            return
        }
        hasFinished = true
        session.stopRunning()
        onVideo(CapturedMedia(fileURL: outputFileURL, kind: .video, fileName: outputFileURL.lastPathComponent))
    }

    private func cropCard(image: UIImage) -> Data? {
        let normalizedImage = UIGraphicsImageRenderer(size: image.size).image { _ in
            image.draw(in: CGRect(origin: .zero, size: image.size))
        }
        guard let cgImage = normalizedImage.cgImage,
              let previewLayer else { return normalizedImage.jpegData(compressionQuality: 0.9) }

        let guide = guideView.convert(guideView.bounds, to: previewView)
        let margin = guide.width * 0.1575
        let cropGuide = guide.insetBy(dx: -margin, dy: -margin)
        let topLeft = previewLayer.captureDevicePointConverted(fromLayerPoint: cropGuide.origin)
        let bottomRight = previewLayer.captureDevicePointConverted(
            fromLayerPoint: CGPoint(x: cropGuide.maxX, y: cropGuide.maxY)
        )
        let normalizedRect = CGRect(
            x: min(topLeft.x, bottomRight.x),
            y: min(topLeft.y, bottomRight.y),
            width: abs(bottomRight.x - topLeft.x),
            height: abs(bottomRight.y - topLeft.y)
        ).intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
        guard normalizedRect.width > 0.05, normalizedRect.height > 0.05 else {
            return normalizedImage.jpegData(compressionQuality: 0.9)
        }
        let pixelRect = CGRect(
            x: normalizedRect.minX * CGFloat(cgImage.width),
            y: normalizedRect.minY * CGFloat(cgImage.height),
            width: normalizedRect.width * CGFloat(cgImage.width),
            height: normalizedRect.height * CGFloat(cgImage.height)
        ).integral
        guard let cropped = cgImage.cropping(to: pixelRect) else {
            return normalizedImage.jpegData(compressionQuality: 0.9)
        }
        return UIImage(cgImage: cropped).jpegData(compressionQuality: 0.9)
    }

    private func save(data: Data, extension: String) -> URL? {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension(`extension`)
        do {
            try data.write(to: url, options: .atomic)
            return url
        } catch {
            return nil
        }
    }

    private static func format(seconds: TimeInterval) -> String {
        let total = Int(seconds)
        return String(format: "%02d:%02d", total / 60, total % 60)
    }
}

final class CardGuideView: UIView {
    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let length = min(rect.width, rect.height) * 0.16
        context.setStrokeColor(UIColor.white.cgColor)
        context.setLineWidth(4)
        context.setLineCap(.round)
        let corners = [
            (CGPoint(x: 0, y: length), CGPoint(x: 0, y: 0), CGPoint(x: length, y: 0)),
            (CGPoint(x: rect.width - length, y: 0), CGPoint(x: rect.width, y: 0), CGPoint(x: rect.width, y: length)),
            (CGPoint(x: 0, y: rect.height - length), CGPoint(x: 0, y: rect.height), CGPoint(x: length, y: rect.height)),
            (CGPoint(x: rect.width - length, y: rect.height), CGPoint(x: rect.width, y: rect.height), CGPoint(x: rect.width, y: rect.height - length))
        ]
        for (first, corner, last) in corners {
            context.move(to: first)
            context.addLine(to: corner)
            context.addLine(to: last)
        }
        context.strokePath()
    }
}
