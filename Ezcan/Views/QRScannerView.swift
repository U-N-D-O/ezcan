import AVFoundation
import SwiftUI
import UIKit

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
    private let sessionQueue = DispatchQueue(label: "com.undu.ezcan.qr-session")
    private let previewView = UIView()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var cameraDevice: AVCaptureDevice?
    private var isConfigured = false
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
        view.backgroundColor = UIColor(red: 0.94, green: 0.97, blue: 0.98, alpha: 1)
        buildView()
        requestCameraAccess()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = previewView.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
        }
    }

    private func buildView() {
        previewView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(previewView)
        NSLayoutConstraint.activate([
            previewView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            previewView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            previewView.topAnchor.constraint(equalTo: view.topAnchor),
            previewView.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])

        let title = UILabel()
        title.translatesAutoresizingMaskIntoConstraints = false
        title.text = "Scan Ezcan Computer"
        title.textColor = UIColor(red: 0.07, green: 0.12, blue: 0.16, alpha: 1)
        title.font = .systemFont(ofSize: 22, weight: .bold)
        title.textAlignment = .center
        view.addSubview(title)

        let instruction = UILabel()
        instruction.translatesAutoresizingMaskIntoConstraints = false
        instruction.text = "Point at the QR code shown on the computer"
        instruction.textColor = UIColor(red: 0.34, green: 0.42, blue: 0.47, alpha: 1)
        instruction.font = .systemFont(ofSize: 15, weight: .medium)
        instruction.textAlignment = .center
        instruction.numberOfLines = 0
        view.addSubview(instruction)

        let frameView = QRFrameView()
        frameView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(frameView)

        var cancelConfiguration = UIButton.Configuration.filled()
        cancelConfiguration.title = "Cancel"
        cancelConfiguration.image = UIImage(systemName: "xmark")
        cancelConfiguration.imagePadding = 6
        cancelConfiguration.baseForegroundColor = UIColor(red: 0.07, green: 0.12, blue: 0.16, alpha: 1)
        cancelConfiguration.baseBackgroundColor = UIColor.white.withAlphaComponent(0.94)
        cancelConfiguration.cornerStyle = .capsule
        cancelConfiguration.background.strokeColor = UIColor(red: 0.10, green: 0.76, blue: 0.78, alpha: 0.42)
        cancelConfiguration.background.strokeWidth = 1
        let cancelButton = UIButton(configuration: cancelConfiguration)
        cancelButton.translatesAutoresizingMaskIntoConstraints = false
        cancelButton.addAction(UIAction { [weak self] _ in
            self?.coordinator.onCancel()
        }, for: .touchUpInside)
        view.addSubview(cancelButton)

        NSLayoutConstraint.activate([
            title.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 22),
            title.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            title.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
            instruction.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 8),
            instruction.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 30),
            instruction.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -30),
            frameView.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            frameView.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            frameView.widthAnchor.constraint(equalTo: view.widthAnchor, multiplier: 0.72),
            frameView.heightAnchor.constraint(equalTo: frameView.widthAnchor),
            cancelButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            cancelButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24)
        ])
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
                        self?.showCameraMessage("Camera access is required in Settings")
                    }
                }
            }
        default:
            showCameraMessage("Camera access is required in Settings")
        }
    }

    private func showCameraMessage(_ message: String) {
        let label = UILabel()
        label.translatesAutoresizingMaskIntoConstraints = false
        label.text = message
        label.textColor = UIColor(red: 0.07, green: 0.12, blue: 0.16, alpha: 1)
        label.textAlignment = .center
        label.numberOfLines = 0
        label.backgroundColor = UIColor.white.withAlphaComponent(0.96)
        label.layer.cornerRadius = 14
        label.layer.borderWidth = 1
        label.layer.borderColor = UIColor(red: 0.90, green: 0.30, blue: 0.44, alpha: 0.65).cgColor
        label.clipsToBounds = true
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
    }

    private func configureScanner() {
        sessionQueue.async { [weak self] in
            guard let self, !self.isConfigured else { return }
            guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                  let input = try? AVCaptureDeviceInput(device: camera),
                  self.session.canAddInput(input) else {
                self.updateStatus("No camera is available")
                return
            }
            let output = AVCaptureMetadataOutput()
            guard self.session.canAddOutput(output) else {
                self.updateStatus("QR scanning is unavailable")
                return
            }
            self.isConfigured = true
            self.cameraDevice = camera
            self.configureContinuousFocus(on: camera)
            self.session.beginConfiguration()
            self.session.addInput(input)
            self.session.addOutput(output)
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]
            self.session.commitConfiguration()

            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                let layer = AVCaptureVideoPreviewLayer(session: self.session)
                layer.videoGravity = .resizeAspectFill
                self.previewView.layer.addSublayer(layer)
                self.previewLayer = layer
                self.view.setNeedsLayout()
                self.view.layoutIfNeeded()
                self.sessionQueue.async { [weak self] in
                    self?.session.startRunning()
                }
            }
        }
    }

    private func updateStatus(_ message: String) {
        DispatchQueue.main.async { [weak self] in
            self?.showCameraMessage(message)
        }
    }

    private func configureContinuousFocus(on camera: AVCaptureDevice) {
        guard camera.isFocusModeSupported(.continuousAutoFocus) else { return }
        do {
            try camera.lockForConfiguration()
            camera.focusMode = .continuousAutoFocus
            if camera.isFocusPointOfInterestSupported {
                camera.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5)
                camera.isSubjectAreaChangeMonitoringEnabled = true
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

    func metadataOutput(
        _ output: AVCaptureMetadataOutput,
        didOutput metadataObjects: [AVMetadataObject],
        from connection: AVCaptureConnection
    ) {
        guard !didScan,
              let code = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let value = code.stringValue else { return }
        didScan = true
        session.stopRunning()
        coordinator.onPayload(value)
    }
}

final class QRFrameView: UIView {
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
        let cornerLength = min(rect.width, rect.height) * 0.18
        context.setShadow(offset: .zero, blur: 10, color: UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 0.8).cgColor)
        context.setStrokeColor(UIColor(red: 0.20, green: 0.90, blue: 0.87, alpha: 1).cgColor)
        context.setLineWidth(4)
        context.setLineCap(.round)
        let corners = [
            (CGPoint(x: 0, y: cornerLength), CGPoint.zero, CGPoint(x: cornerLength, y: 0)),
            (CGPoint(x: rect.width - cornerLength, y: 0), CGPoint(x: rect.width, y: 0), CGPoint(x: rect.width, y: cornerLength)),
            (CGPoint(x: 0, y: rect.height - cornerLength), CGPoint(x: 0, y: rect.height), CGPoint(x: cornerLength, y: rect.height)),
            (CGPoint(x: rect.width - cornerLength, y: rect.height), CGPoint(x: rect.width, y: rect.height), CGPoint(x: rect.width, y: rect.height - cornerLength))
        ]
        for (start, corner, end) in corners {
            context.move(to: start)
            context.addLine(to: corner)
            context.addLine(to: end)
        }
        context.strokePath()
    }
}