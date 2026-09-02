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
    private let previewView = UIView()
    private var previewLayer: AVCaptureVideoPreviewLayer?
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
        view.backgroundColor = .black
        buildView()
        requestCameraAccess()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = previewView.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning {
            session.stopRunning()
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
        title.text = "SCAN EZCAN COMPUTER"
        title.textColor = .white
        title.font = .systemFont(ofSize: 22, weight: .bold)
        title.textAlignment = .center
        view.addSubview(title)

        let instruction = UILabel()
        instruction.translatesAutoresizingMaskIntoConstraints = false
        instruction.text = "Point at the QR code shown on the computer"
        instruction.textColor = UIColor.white.withAlphaComponent(0.85)
        instruction.font = .systemFont(ofSize: 15, weight: .medium)
        instruction.textAlignment = .center
        instruction.numberOfLines = 0
        view.addSubview(instruction)

        let frameView = QRFrameView()
        frameView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(frameView)

        var cancelConfiguration = UIButton.Configuration.plain()
        cancelConfiguration.title = "Cancel"
        cancelConfiguration.image = UIImage(systemName: "xmark")
        cancelConfiguration.imagePadding = 6
        cancelConfiguration.baseForegroundColor = .white
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
        label.textColor = .white
        label.textAlignment = .center
        label.numberOfLines = 0
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
    }

    private func configureScanner() {
        guard !isConfigured,
              let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: camera),
              session.canAddInput(input) else {
            showCameraMessage("No camera is available")
            return
        }
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else {
            showCameraMessage("QR scanning is unavailable")
            return
        }
        isConfigured = true
        session.addInput(input)
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        previewView.layer.addSublayer(layer)
        previewLayer = layer
        session.startRunning()
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
    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let cornerLength = min(rect.width, rect.height) * 0.18
        context.setStrokeColor(UIColor.white.cgColor)
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