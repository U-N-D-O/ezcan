import AVFoundation
import ImageIO
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

final class GuidedCameraController: UIViewController, AVCapturePhotoCaptureDelegate, AVCaptureFileOutputRecordingDelegate, AVCaptureVideoDataOutputSampleBufferDelegate {
    private enum LensMode {
        case automatic
        case standard
        case closeUp
    }

    private let titleText: String
    private let mode: GuidedCameraView.Mode
    private let onPhoto: (CapturedMedia) -> Void
    private let onVideo: (CapturedMedia) -> Void
    private let onBack: () -> Void
    private let onNext: () -> Void
    private let onCancel: () -> Void

    private let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "com.undu.ezcan.camera-session")
    private let photoOutput = AVCapturePhotoOutput()
    private let movieOutput = AVCaptureMovieFileOutput()
    private let videoDataOutput = AVCaptureVideoDataOutput()
    private let analysisQueue = DispatchQueue(label: "com.undu.ezcan.camera-analysis")
    private let photoProcessingQueue = DispatchQueue(label: "com.undu.ezcan.photo-processing", qos: .userInitiated)
    private let previewView = UIView()
    private let guideView = CardGuideView()
    private let timerLabel = UILabel()
    private let statusLabel = UILabel()
    private let zoomControl = UISegmentedControl(items: ["1X", "2X"])
    private let lensControl = UISegmentedControl(items: ["AUTO", "MACRO"])
    private weak var captureButton: UIButton?
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var cameraDevice: AVCaptureDevice?
    private var cameraInput: AVCaptureDeviceInput?
    private var standardCamera: AVCaptureDevice?
    private var closeUpCamera: AVCaptureDevice?
    private var recordingTimer: Timer?
    private var recordingStartedAt: Date?
    private var isRecording = false
    private var isConfigured = false
    private var hasFinished = false
    private var lensMode = LensMode.automatic
    private var closeUpFrames = 0
    private var standardFrames = 0
    private var nextAutomaticSwitchDate = Date.distantPast
    private var requestedZoomFactor: CGFloat = 1
    private var pendingCropRect: CGRect?
    private var photoCaptureInFlight = false

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
        view.backgroundColor = UIColor(red: 0.025, green: 0.055, blue: 0.11, alpha: 1)
        buildView()
        requestCameraAccess()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = previewView.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        recordingTimer?.invalidate()
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
        }
    }

    private func buildView() {
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
        shade.backgroundColor = UIColor(red: 0.01, green: 0.03, blue: 0.06, alpha: 0.34)
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
        let guideWidth = guideView.widthAnchor.constraint(equalTo: view.widthAnchor, multiplier: 0.76)
        guideWidth.priority = .defaultHigh
        NSLayoutConstraint.activate([
            guideView.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            guideView.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -18),
            guideWidth,
            guideView.heightAnchor.constraint(equalTo: guideView.widthAnchor, multiplier: 1.4),
            guideView.heightAnchor.constraint(lessThanOrEqualTo: view.safeAreaLayoutGuide.heightAnchor, multiplier: 0.52)
        ])

        let titleLabel = makeLabel(titleText.uppercased(), size: 27, weight: .bold)
        let subtitleLabel = makeLabel(
            mode == .photo ? "Fit the whole card inside the corners" : "Move slowly around the card surface",
            size: 14,
            weight: .medium
        )
        subtitleLabel.textColor = UIColor(red: 0.52, green: 0.64, blue: 0.77, alpha: 1)
        subtitleLabel.numberOfLines = 0

        timerLabel.translatesAutoresizingMaskIntoConstraints = false
        timerLabel.text = "00:00"
        timerLabel.textColor = UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 1)
        timerLabel.font = UIFont.monospacedDigitSystemFont(ofSize: 17, weight: .semibold)
        timerLabel.textAlignment = .center
        timerLabel.isHidden = mode == .photo
        view.addSubview(timerLabel)

        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.text = "Preparing camera..."
        statusLabel.textColor = UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 1)
        statusLabel.font = .systemFont(ofSize: 13)
        statusLabel.textAlignment = .center
        statusLabel.numberOfLines = 0
        statusLabel.backgroundColor = UIColor(red: 0.025, green: 0.065, blue: 0.115, alpha: 0.88)
        statusLabel.layer.cornerRadius = 14
        statusLabel.layer.borderWidth = 1
        statusLabel.layer.borderColor = UIColor(red: 0.13, green: 0.28, blue: 0.40, alpha: 1).cgColor
        statusLabel.clipsToBounds = true
        view.addSubview(statusLabel)

        configureSegmentedControl(zoomControl)
        configureSegmentedControl(lensControl)
        zoomControl.addTarget(self, action: #selector(zoomChanged), for: .valueChanged)
        lensControl.addTarget(self, action: #selector(lensModeChanged), for: .valueChanged)
        view.addSubview(zoomControl)
        view.addSubview(lensControl)

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
        captureButton.layer.borderWidth = 4
        captureButton.layer.borderColor = UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 0.8).cgColor
        captureButton.layer.shadowColor = UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 1).cgColor
        captureButton.layer.shadowRadius = 14
        captureButton.layer.shadowOpacity = 0.7
        captureButton.layer.shadowOffset = .zero
        captureButton.addAction(UIAction { [weak self, weak captureButton] _ in
            guard let captureButton else { return }
            self?.capturePressed(captureButton)
        }, for: .touchUpInside)
        self.captureButton = captureButton
        captureButton.isEnabled = false
        view.addSubview(captureButton)

        let hint = makeLabel(
            mode == .photo ? "Photo includes an approximate 1 cm border" : "1080p HD video, up to 30 seconds",
            size: 12,
            weight: .medium
        )
        hint.textColor = UIColor.white.withAlphaComponent(0.75)

        NSLayoutConstraint.activate([
            titleLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 18),
            titleLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            subtitleLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 5),
            subtitleLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            subtitleLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
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
            zoomControl.trailingAnchor.constraint(equalTo: captureButton.leadingAnchor, constant: -12),
            zoomControl.centerYAnchor.constraint(equalTo: captureButton.centerYAnchor),
            zoomControl.widthAnchor.constraint(equalToConstant: 82),
            zoomControl.heightAnchor.constraint(equalToConstant: 34),
            lensControl.leadingAnchor.constraint(equalTo: captureButton.trailingAnchor, constant: 12),
            lensControl.centerYAnchor.constraint(equalTo: captureButton.centerYAnchor),
            lensControl.widthAnchor.constraint(equalToConstant: 94),
            lensControl.heightAnchor.constraint(equalToConstant: 34),
            hint.topAnchor.constraint(equalTo: captureButton.bottomAnchor, constant: 12),
            hint.centerXAnchor.constraint(equalTo: view.centerXAnchor)
        ])
    }

    private func configureSegmentedControl(_ control: UISegmentedControl) {
        control.translatesAutoresizingMaskIntoConstraints = false
        control.selectedSegmentIndex = 0
        control.selectedSegmentTintColor = UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 1)
        control.setTitleTextAttributes([.foregroundColor: UIColor.white], for: .normal)
        control.setTitleTextAttributes([.foregroundColor: UIColor(red: 0.01, green: 0.08, blue: 0.11, alpha: 1)], for: .selected)
    }

    private func makeLabel(_ text: String, size: CGFloat, weight: UIFont.Weight) -> UILabel {
        let label = UILabel()
        label.translatesAutoresizingMaskIntoConstraints = false
        label.text = text
        label.textColor = .white
        label.font = .systemFont(ofSize: size, weight: weight)
        label.textAlignment = .center
        view.addSubview(label)
        return label
    }

    private func makeButton(title: String, imageName: String) -> UIButton {
        var configuration = UIButton.Configuration.filled()
        configuration.title = title
        configuration.image = UIImage(systemName: imageName)
        configuration.imagePadding = 5
        configuration.baseForegroundColor = .white
        configuration.baseBackgroundColor = UIColor(red: 0.075, green: 0.145, blue: 0.23, alpha: 0.9)
        configuration.cornerStyle = .capsule
        configuration.background.strokeColor = UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 0.42)
        configuration.background.strokeWidth = 1
        configuration.contentInsets = NSDirectionalEdgeInsets(top: 8, leading: 13, bottom: 8, trailing: 13)
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
        sessionQueue.async { [weak self] in
            guard let self, !self.isConfigured else { return }
            self.session.beginConfiguration()
            self.session.sessionPreset = self.mode == .photo ? .photo : .hd1920x1080

            guard let camera = Self.preferredStandardCamera(),
                  let videoInput = try? AVCaptureDeviceInput(device: camera),
                  self.session.canAddInput(videoInput) else {
                self.session.commitConfiguration()
                self.updateStatus("No camera is available")
                return
            }
            self.session.addInput(videoInput)
            self.cameraDevice = camera
            self.cameraInput = videoInput
            self.standardCamera = camera
            self.closeUpCamera = AVCaptureDevice.default(.builtInUltraWideCamera, for: .video, position: .back)
            self.configureContinuousFocus(on: camera)
            self.applyZoom(to: camera, factor: self.requestedZoomFactor)

            if self.mode == .video {
                self.videoDataOutput.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange]
                self.videoDataOutput.alwaysDiscardsLateVideoFrames = true
                self.videoDataOutput.setSampleBufferDelegate(self, queue: self.analysisQueue)
                if self.session.canAddOutput(self.videoDataOutput) {
                    self.session.addOutput(self.videoDataOutput)
                }
            }

            if self.mode == .photo {
                guard self.session.canAddOutput(self.photoOutput) else {
                    self.session.commitConfiguration()
                    self.updateStatus("Photo capture is unavailable")
                    return
                }
                self.session.addOutput(self.photoOutput)
                if self.photoOutput.isHighResolutionCaptureSupported {
                    self.photoOutput.isHighResolutionCaptureEnabled = true
                }
            } else {
                guard self.session.canAddOutput(self.movieOutput) else {
                    self.session.commitConfiguration()
                    self.updateStatus("Video capture is unavailable")
                    return
                }
                self.session.addOutput(self.movieOutput)
                if let microphone = AVCaptureDevice.default(for: .audio),
                   let audioInput = try? AVCaptureDeviceInput(device: microphone),
                   self.session.canAddInput(audioInput) {
                    self.session.addInput(audioInput)
                }
            }

            self.session.commitConfiguration()
            self.isConfigured = true
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                let layer = AVCaptureVideoPreviewLayer(session: self.session)
                layer.videoGravity = .resizeAspectFill
                self.previewView.layer.addSublayer(layer)
                self.previewLayer = layer
                self.view.setNeedsLayout()
                self.view.layoutIfNeeded()
                self.setPortraitOrientation()
                self.lensControl.setEnabled(self.closeUpCamera != nil, forSegmentAt: 1)
                self.captureButton?.isEnabled = false
                self.statusLabel.text = self.closeUpCamera == nil ? "Ready · Macro unavailable" : "Ready · Auto lens"
            }
            self.session.startRunning()
            DispatchQueue.main.async { [weak self] in
                self?.captureButton?.isEnabled = self?.session.isRunning == true
            }
        }
    }

    private func updateStatus(_ message: String) {
        DispatchQueue.main.async { [weak self] in
            self?.statusLabel.text = message
        }
    }

    private static func preferredStandardCamera() -> AVCaptureDevice? {
        AVCaptureDevice.default(.builtInTripleCamera, for: .video, position: .back)
            ?? AVCaptureDevice.default(.builtInDualWideCamera, for: .video, position: .back)
            ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
    }

    private func configureContinuousFocus(on camera: AVCaptureDevice) {
        do {
            try camera.lockForConfiguration()
            if camera.isFocusModeSupported(.continuousAutoFocus) {
                camera.focusMode = .continuousAutoFocus
            } else if camera.isFocusModeSupported(.autoFocus) {
                camera.focusMode = .autoFocus
            }
            if camera.isAutoFocusRangeRestrictionSupported {
                camera.autoFocusRangeRestriction = lensMode == .closeUp ? .near : .none
            }
            if camera.isFocusPointOfInterestSupported {
                camera.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5)
                camera.isSubjectAreaChangeMonitoringEnabled = true
            }
            if camera.isSmoothAutoFocusSupported {
                camera.isSmoothAutoFocusEnabled = true
            }
            if camera.isExposureModeSupported(.continuousAutoExposure) {
                camera.exposureMode = .continuousAutoExposure
                if camera.isExposurePointOfInterestSupported {
                    camera.exposurePointOfInterest = CGPoint(x: 0.5, y: 0.5)
                }
            }
            camera.unlockForConfiguration()
        } catch {
            updateStatus("Camera focus is unavailable")
        }
    }

    private func applyZoom(to camera: AVCaptureDevice, factor: CGFloat) {
        guard camera.isVideoZoomSupported else { return }
        let clampedFactor = min(max(factor, camera.minAvailableVideoZoomFactor), camera.maxAvailableVideoZoomFactor)
        do {
            try camera.lockForConfiguration()
            camera.videoZoomFactor = clampedFactor
            camera.unlockForConfiguration()
        } catch {
            updateStatus("Zoom is unavailable")
        }
    }

    @objc private func zoomChanged() {
        requestedZoomFactor = zoomControl.selectedSegmentIndex == 1 ? 2 : 1
        CrashReporter.shared.record("Zoom changed to \(Int(requestedZoomFactor))X")
        sessionQueue.async { [weak self] in
            guard let self, let camera = self.cameraDevice else { return }
            self.applyZoom(to: camera, factor: self.requestedZoomFactor)
        }
    }

    @objc private func lensModeChanged() {
        let selectedMode: LensMode
        switch lensControl.selectedSegmentIndex {
        case 1:
            selectedMode = .closeUp
        default:
            selectedMode = .automatic
        }

        guard selectedMode != .closeUp || closeUpCamera != nil else {
            lensControl.selectedSegmentIndex = 0
            updateStatus("Macro camera is unavailable on this iPhone")
            return
        }
        lensMode = selectedMode
        closeUpFrames = 0
        standardFrames = 0
        nextAutomaticSwitchDate = Date().addingTimeInterval(0.8)

        switch selectedMode {
        case .automatic:
            updateStatus("Auto lens · watching focus")
            switchCameraIfNeeded(to: false)
        case .closeUp:
            updateStatus("Macro camera · close focus")
            switchCameraIfNeeded(to: true)
        }
    }

    private func switchCameraIfNeeded(to closeUp: Bool) {
        sessionQueue.async { [weak self] in
            guard let self,
                  !self.hasFinished,
                  !self.isRecording,
                  let targetCamera = closeUp ? self.closeUpCamera : self.standardCamera,
                  targetCamera.uniqueID != self.cameraDevice?.uniqueID,
                  let targetInput = try? AVCaptureDeviceInput(device: targetCamera) else { return }

            self.session.beginConfiguration()
            if let currentInput = self.cameraInput {
                self.session.removeInput(currentInput)
            }
            guard self.session.canAddInput(targetInput) else {
                if let currentInput = self.cameraInput, self.session.canAddInput(currentInput) {
                    self.session.addInput(currentInput)
                }
                self.session.commitConfiguration()
                self.updateStatus(closeUp ? "Macro camera is unavailable" : "Standard camera is unavailable")
                return
            }
            self.session.addInput(targetInput)
            self.cameraInput = targetInput
            self.cameraDevice = targetCamera
            self.configureContinuousFocus(on: targetCamera)
            self.applyZoom(to: targetCamera, factor: self.requestedZoomFactor)
            self.session.commitConfiguration()
            self.nextAutomaticSwitchDate = Date().addingTimeInterval(1.2)

            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                let message = closeUp ? "Macro camera · close focus" : "Standard camera · 1X"
                if self.lensMode == .automatic {
                    self.statusLabel.text = closeUp ? "Auto lens · macro" : "Auto lens · standard"
                } else {
                    self.statusLabel.text = message
                }
            }
        }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard lensMode == .automatic,
              !isRecording,
              closeUpCamera != nil,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer),
              let camera = cameraDevice else { return }

        let sharpness = Self.centerSharpness(of: pixelBuffer)
        let lensPosition = camera.lensPosition
        let looksTooClose = lensPosition > 0.82 || (lensPosition > 0.64 && sharpness < 22)
        let looksComfortableOnStandard = lensPosition < 0.58 && sharpness > 28

        if camera.uniqueID == standardCamera?.uniqueID {
            closeUpFrames = looksTooClose ? closeUpFrames + 1 : 0
            standardFrames = 0
            if closeUpFrames >= 7, Date() >= nextAutomaticSwitchDate {
                closeUpFrames = 0
                switchCameraIfNeeded(to: true)
            }
        } else {
            standardFrames = looksComfortableOnStandard ? standardFrames + 1 : 0
            closeUpFrames = 0
            if standardFrames >= 12, Date() >= nextAutomaticSwitchDate {
                standardFrames = 0
                switchCameraIfNeeded(to: false)
            }
        }
    }

    private static func centerSharpness(of pixelBuffer: CVPixelBuffer) -> Double {
        guard CVPixelBufferGetPlaneCount(pixelBuffer) > 0 else { return 0 }
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let baseAddress = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0) else { return 0 }

        let width = CVPixelBufferGetWidthOfPlane(pixelBuffer, 0)
        let height = CVPixelBufferGetHeightOfPlane(pixelBuffer, 0)
        let bytesPerRow = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
        let pixels = baseAddress.assumingMemoryBound(to: UInt8.self)
        let left = width / 5
        let right = width * 4 / 5
        let top = height / 5
        let bottom = height * 4 / 5
        let sampleStride = 4
        var sum = 0.0
        var sumSquared = 0.0
        var count = 0.0

        for y in Swift.stride(from: top + 1, through: bottom - 2, by: sampleStride) {
            for x in Swift.stride(from: left + 1, through: right - 2, by: sampleStride) {
                let index = y * bytesPerRow + x
                let laplacian = Double(4 * Int(pixels[index]) - Int(pixels[index - 1]) - Int(pixels[index + 1]) - Int(pixels[index - bytesPerRow]) - Int(pixels[index + bytesPerRow]))
                sum += laplacian
                sumSquared += laplacian * laplacian
                count += 1
            }
        }
        guard count > 0 else { return 0 }
        let mean = sum / count
        return max(0, sumSquared / count - mean * mean)
    }

    private func setPortraitOrientation() {
        let connections = [
            previewLayer?.connection,
            photoOutput.connection(with: .video),
            movieOutput.connection(with: .video)
        ].compactMap { $0 }
        for connection in connections where connection.isVideoOrientationSupported {
            connection.videoOrientation = .portrait
        }
    }

    private func capturePressed(_ button: UIButton) {
        if mode == .photo {
            capturePhoto()
        } else if isRecording {
            stopRecording(button)
        } else {
            startRecording(button)
        }
    }

    private func capturePhoto() {
        guard !hasFinished, !photoCaptureInFlight else { return }
        photoCaptureInFlight = true
        hasFinished = true
        CrashReporter.shared.record("Starting photo capture")
        pendingCropRect = previewCropRect()
        sessionQueue.async { [weak self] in
            guard let self else { return }
            guard self.session.isRunning,
                  self.photoOutput.connection(with: .video) != nil else {
                self.photoCaptureFailed("Camera session was not ready")
                return
            }
            let settings: AVCapturePhotoSettings
            if self.photoOutput.availablePhotoCodecTypes.contains(AVVideoCodecType.jpeg) {
                settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
            } else {
                settings = AVCapturePhotoSettings()
            }
            settings.isHighResolutionPhotoEnabled = self.photoOutput.isHighResolutionCaptureEnabled
            settings.photoQualityPrioritization = self.photoOutput.maxPhotoQualityPrioritization
            if #available(iOS 16.0, *) {
                settings.maxPhotoDimensions = self.photoOutput.maxPhotoDimensions
            }
            if let connection = self.photoOutput.connection(with: .video), connection.isVideoStabilizationSupported {
                connection.preferredVideoStabilizationMode = .auto
            }
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
        updateStatus("Capturing high-quality card image...")
    }

    private func previewCropRect() -> CGRect? {
        guard let previewLayer else { return nil }
        let guideRect = previewView.convert(guideView.bounds, from: guideView)
        let normalizedRect = previewLayer.metadataOutputRectConverted(fromLayerRect: guideRect)
        guard normalizedRect.width > 0.05, normalizedRect.height > 0.05 else { return nil }
        return normalizedRect.intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
    }

    private func photoCaptureFailed(_ message: String) {
        CrashReporter.shared.record("Photo capture failed: \(message)")
        DispatchQueue.main.async { [weak self] in
            self?.hasFinished = false
            self?.photoCaptureInFlight = false
            self?.captureButton?.isEnabled = true
            self?.updateStatus("Could not capture photo")
        }
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
        button.backgroundColor = UIColor(red: 0.90, green: 0.22, blue: 0.43, alpha: 1)
        recordingTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self, weak button] _ in
            guard let self, let started = self.recordingStartedAt else { return }
            let elapsed = Date().timeIntervalSince(started)
            self.timerLabel.text = Self.timeString(elapsed)
            if elapsed >= 30 { self.stopRecording(button) }
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
        if let error {
            CrashReporter.shared.record("Photo capture failed: \(error.localizedDescription)")
        }
        guard error == nil, let data = photo.fileDataRepresentation() else {
            CrashReporter.shared.record("Photo data was unavailable")
            DispatchQueue.main.async { [weak self] in
                self?.hasFinished = false
                self?.photoCaptureInFlight = false
                self?.updateStatus("Could not capture photo")
            }
            return
        }
        CrashReporter.shared.record("Photo captured; received \(data.count) bytes; saving JPEG")
        let cropRect = pendingCropRect
        photoProcessingQueue.async { [weak self] in
            autoreleasepool {
                guard let self,
                      let jpegData = Self.processPhotoData(data, cropRect: cropRect),
                      let url = self.save(jpegData, extension: "jpg") else {
                    CrashReporter.shared.record("Photo JPEG could not be saved")
                    DispatchQueue.main.async { [weak self] in
                        self?.hasFinished = false
                        self?.photoCaptureInFlight = false
                        self?.updateStatus("Could not process photo")
                    }
                    return
                }
                self.sessionQueue.async { [weak self] in
                    self?.session.stopRunning()
                    DispatchQueue.main.async { [weak self] in
                        guard let self else { return }
                        self.photoCaptureInFlight = false
                        self.onPhoto(CapturedMedia(fileURL: url, kind: .image, fileName: url.lastPathComponent))
                    }
                }
            }
        }
    }

    private static let outputLongEdge = 1600

    private static func processPhotoData(_ data: Data, cropRect: CGRect?) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, [
                  kCGImageSourceShouldCache: false
              ] as CFDictionary),
              let sourceProperties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let sourceWidth = sourceProperties[kCGImagePropertyPixelWidth] as? Int,
              let sourceHeight = sourceProperties[kCGImagePropertyPixelHeight] as? Int,
              let image = CGImageSourceCreateThumbnailAtIndex(
                source,
                0,
                [
                    kCGImageSourceCreateThumbnailFromImageAlways: true,
                    kCGImageSourceCreateThumbnailWithTransform: true,
                    kCGImageSourceShouldCache: false,
                    kCGImageSourceThumbnailMaxPixelSize: thumbnailMaxPixelSize(
                        width: sourceWidth,
                        height: sourceHeight,
                        cropRect: cropRect
                    )
                ] as CFDictionary
              ) else { return nil }

        let croppedImage = crop(image, to: cropRect)
        let outputImage = resize(croppedImage, toLongEdge: outputLongEdge)
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, "public.jpeg" as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(
            destination,
            outputImage,
            [kCGImageDestinationLossyCompressionQuality: 0.98] as CFDictionary
        )
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }

    private static func thumbnailMaxPixelSize(width: Int, height: Int, cropRect: CGRect?) -> Int {
        guard let cropRect else { return outputLongEdge }
        let cropWidth = CGFloat(width) * cropRect.width
        let cropHeight = CGFloat(height) * cropRect.height
        let cropLongEdge = max(cropWidth, cropHeight)
        guard cropLongEdge > 1 else { return outputLongEdge }
        let sourceLongEdge = CGFloat(max(width, height))
        return max(outputLongEdge, Int(ceil(CGFloat(outputLongEdge) * sourceLongEdge / cropLongEdge)))
    }

    private static func resize(_ image: CGImage, toLongEdge longEdge: Int) -> CGImage {
        let sourceLongEdge = max(image.width, image.height)
        guard sourceLongEdge > 0, sourceLongEdge != longEdge else { return image }
        let scale = CGFloat(longEdge) / CGFloat(sourceLongEdge)
        let width = max(1, Int((CGFloat(image.width) * scale).rounded()))
        let height = max(1, Int((CGFloat(image.height) * scale).rounded()))
        guard let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return image }
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        return context.makeImage() ?? image
    }

    private static func crop(_ image: CGImage, to normalizedRect: CGRect?) -> CGImage {
        guard let normalizedRect else { return image }
        let pixelRect = CGRect(
            x: normalizedRect.minX * CGFloat(image.width),
            y: normalizedRect.minY * CGFloat(image.height),
            width: normalizedRect.width * CGFloat(image.width),
            height: normalizedRect.height * CGFloat(image.height)
        ).integral.intersection(CGRect(x: 0, y: 0, width: image.width, height: image.height))
        guard pixelRect.width > 32, pixelRect.height > 32 else { return image }
        return image.cropping(to: pixelRect) ?? image
    }

    func fileOutput(
        _ output: AVCaptureFileOutput,
        didFinishRecordingTo outputFileURL: URL,
        from connections: [AVCaptureConnection],
        error: Error?
    ) {
        guard error == nil else {
            updateStatus("Could not save video")
            return
        }
        hasFinished = true
        sessionQueue.async { [weak self] in
            self?.session.stopRunning()
            DispatchQueue.main.async { [weak self] in
                self?.onVideo(CapturedMedia(fileURL: outputFileURL, kind: .video, fileName: outputFileURL.lastPathComponent))
            }
        }
    }

    private func save(_ data: Data, extension fileExtension: String) -> URL? {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension(fileExtension)
        do {
            try data.write(to: url, options: .atomic)
            return url
        } catch {
            return nil
        }
    }

    private static func timeString(_ seconds: TimeInterval) -> String {
        let total = Int(seconds)
        return String(format: "%02d:%02d", total / 60, total % 60)
    }
}

final class CardGuideView: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isOpaque = false
        isUserInteractionEnabled = false
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        backgroundColor = .clear
        isOpaque = false
        isUserInteractionEnabled = false
    }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let length = min(rect.width, rect.height) * 0.16
        context.setShadow(offset: .zero, blur: 8, color: UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 0.75).cgColor)
        context.setStrokeColor(UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 1).cgColor)
        context.setLineWidth(4)
        context.setLineCap(.round)
        let corners = [
            (CGPoint(x: 0, y: length), CGPoint(x: 0, y: 0), CGPoint(x: length, y: 0)),
            (CGPoint(x: rect.width - length, y: 0), CGPoint(x: rect.width, y: 0), CGPoint(x: rect.width, y: length)),
            (CGPoint(x: 0, y: rect.height - length), CGPoint(x: 0, y: rect.height), CGPoint(x: length, y: rect.height)),
            (CGPoint(x: rect.width - length, y: rect.height), CGPoint(x: rect.width, y: rect.height), CGPoint(x: rect.width, y: rect.height - length))
        ]
        for (start, corner, end) in corners {
            context.move(to: start)
            context.addLine(to: corner)
            context.addLine(to: end)
        }
        context.strokePath()
    }
}