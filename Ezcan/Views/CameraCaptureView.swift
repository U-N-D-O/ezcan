import AVFoundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct CameraCaptureView: UIViewControllerRepresentable {
    let mediaType: UTType
    let onCapture: (CapturedMedia) -> Void
    let onCancel: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onCapture: onCapture, onCancel: onCancel)
    }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let controller = UIImagePickerController()
        controller.sourceType = .camera
        controller.mediaTypes = [mediaType.identifier]
        controller.videoQuality = .typeHigh
        controller.videoMaximumDuration = 30
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onCapture: (CapturedMedia) -> Void
        let onCancel: () -> Void

        init(onCapture: @escaping (CapturedMedia) -> Void, onCancel: @escaping () -> Void) {
            self.onCapture = onCapture
            self.onCancel = onCancel
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            onCancel()
        }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            if let image = info[.originalImage] as? UIImage,
               let data = image.jpegData(compressionQuality: 0.95),
               let media = save(data: data, fileExtension: "jpg", kind: .image) {
                onCapture(media)
            } else if let sourceURL = info[.mediaURL] as? URL,
                      let media = copy(sourceURL: sourceURL, fileExtension: "mov", kind: .video) {
                onCapture(media)
            } else {
                onCancel()
            }
        }

        private func save(data: Data, fileExtension: String, kind: CapturedMedia.Kind) -> CapturedMedia? {
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent(UUID().uuidString)
                .appendingPathExtension(fileExtension)
            do {
                try data.write(to: url, options: .atomic)
                return CapturedMedia(fileURL: url, kind: kind, fileName: url.lastPathComponent)
            } catch {
                return nil
            }
        }

        private func copy(sourceURL: URL, fileExtension: String, kind: CapturedMedia.Kind) -> CapturedMedia? {
            let destination = FileManager.default.temporaryDirectory
                .appendingPathComponent(UUID().uuidString)
                .appendingPathExtension(fileExtension)
            do {
                try FileManager.default.copyItem(at: sourceURL, to: destination)
                return CapturedMedia(fileURL: destination, kind: kind, fileName: destination.lastPathComponent)
            } catch {
                return nil
            }
        }
    }
}
