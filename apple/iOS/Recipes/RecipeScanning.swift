import SwiftUI
import UIKit
import Vision
import VisionKit

/// Reads the words in photos of a recipe on the phone itself (Apple's Vision), in reading order. A page laid out in
/// two columns (ingredients beside the method, as many cookbooks do) is read a column at a time.
enum TextReader {
    static func read(_ images: [UIImage]) async -> String {
        var pages: [String] = []
        for img in images {
            pages.append(await read(img))
        }
        return pages.filter { !$0.isEmpty }.joined(separator: "\n")
    }

    private struct Line: Sendable {
        let text: String
        let box: CGRect  // Vision's normalised box: origin bottom-left
        var top: CGFloat { box.maxY }
    }

    private static func read(_ image: UIImage) async -> String {
        guard let cg = image.cgImage else { return "" }
        let orient = orientation(image.imageOrientation)
        let lines: [Line] = await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            request.automaticallyDetectsLanguage = true
            try? VNImageRequestHandler(cgImage: cg, orientation: orient).perform([request])
            return (request.results ?? []).compactMap { o -> Line? in
                guard let best = o.topCandidates(1).first else { return nil }
                return Line(text: best.string, box: o.boundingBox)
            }
        }.value
        return ordered(lines).map(\.text).joined(separator: "\n")
    }

    /// Top to bottom; when the page has two columns, the left one first, with anything spanning both kept in place.
    private static func ordered(_ lines: [Line]) -> [Line] {
        let byTop = { (a: Line, b: Line) in abs(a.top - b.top) < 0.008 ? a.box.minX < b.box.minX : a.top > b.top }
        let left = lines.filter { $0.box.maxX <= 0.56 }
        let right = lines.filter { $0.box.minX >= 0.44 && $0.box.maxX > 0.56 }
        guard left.count >= 3, right.count >= 3 else { return lines.sorted(by: byTop) }
        let columnsTop = max(left.map(\.top).max() ?? 1, right.map(\.top).max() ?? 1)
        let columnsBottom = min(left.map(\.box.minY).min() ?? 0, right.map(\.box.minY).min() ?? 0)
        let spanning = lines.filter { l in !left.contains { $0.box == l.box } && !right.contains { $0.box == l.box } }
        let above = spanning.filter { $0.box.minY >= columnsTop - 0.01 }
        let below = spanning.filter { $0.top <= columnsBottom + 0.01 }
        let between = spanning.filter { l in !above.contains { $0.box == l.box } && !below.contains { $0.box == l.box } }
        return above.sorted(by: byTop) + left.sorted(by: byTop) + right.sorted(by: byTop) + (between + below).sorted(by: byTop)
    }

    private static func orientation(_ o: UIImage.Orientation) -> CGImagePropertyOrientation {
        switch o {
        case .up: .up
        case .down: .down
        case .left: .left
        case .right: .right
        case .upMirrored: .upMirrored
        case .downMirrored: .downMirrored
        case .leftMirrored: .leftMirrored
        case .rightMirrored: .rightMirrored
        @unknown default: .up
        }
    }
}

extension UIImage {
    /// A JPEG no bigger than `max` pixels on its long side, for uploading.
    func jpeg(max side: CGFloat = 1600, quality: CGFloat = 0.85) -> Data? {
        let longest = Swift.max(size.width, size.height)
        let scale = longest > side ? side / longest : 1
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let img = UIGraphicsImageRenderer(size: target, format: format).image { _ in draw(in: CGRect(origin: .zero, size: target)) }
        return img.jpegData(compressionQuality: quality)
    }
}

/// The system document scanner: finds the page edges, flattens and crops each page.
struct DocumentScanner: UIViewControllerRepresentable {
    var onScan: ([UIImage]) -> Void
    var onCancel: () -> Void

    static var isAvailable: Bool { VNDocumentCameraViewController.isSupported }

    func makeUIViewController(context: Context) -> VNDocumentCameraViewController {
        let vc = VNDocumentCameraViewController()
        vc.delegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: VNDocumentCameraViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, VNDocumentCameraViewControllerDelegate {
        let parent: DocumentScanner
        init(_ parent: DocumentScanner) { self.parent = parent }

        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFinishWith scan: VNDocumentCameraScan) {
            parent.onScan((0..<scan.pageCount).map { scan.imageOfPage(at: $0) })
        }

        func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) { parent.onCancel() }

        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFailWithError error: Error) {
            parent.onCancel()
        }
    }
}

/// The camera, for taking a recipe's picture.
struct CameraPicker: UIViewControllerRepresentable {
    var onPick: (UIImage) -> Void
    @Environment(\.dismiss) private var dismiss

    static var isAvailable: Bool { UIImagePickerController.isSourceTypeAvailable(.camera) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let vc = UIImagePickerController()
        vc.sourceType = .camera
        vc.delegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraPicker
        init(_ parent: CameraPicker) { self.parent = parent }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let img = info[.originalImage] as? UIImage { parent.onPick(img) }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { parent.dismiss() }
    }
}
