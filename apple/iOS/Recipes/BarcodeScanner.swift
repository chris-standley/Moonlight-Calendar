import SwiftUI
import VisionKit

/// The camera, looking for the barcode on the back of a book. Book barcodes are EAN-13 numbers starting 978 or 979
/// (the ISBN); other barcodes, like a supermarket price label, are ignored.
struct BookBarcodeScanner: View {
    var onFound: (String) -> Void
    var onSkip: () -> Void
    var onCancel: () -> Void

    static var isAvailable: Bool { DataScannerViewController.isSupported && DataScannerViewController.isAvailable }

    var body: some View {
        NavigationStack {
            BarcodeCamera(onFound: onFound)
                .ignoresSafeArea()
                .overlay(alignment: .bottom) {
                    VStack(spacing: 14) {
                        Text("Point the camera at the barcode on the back of the cookbook.")
                            .font(Theme.text(.headline, .bold)).multilineTextAlignment(.center)
                            .foregroundStyle(.white)
                        Button("No barcode? Scan the pages", action: onSkip)
                            .font(Theme.text(.subheadline, .bold))
                            .buttonStyle(.borderedProminent).tint(.white.opacity(0.25))
                    }
                    .padding(20)
                    .frame(maxWidth: .infinity)
                    .background(.black.opacity(0.55))
                }
                .navigationTitle("Find the book")
                .navigationBarTitleDisplayMode(.inline)
                .toolbarBackground(.visible, for: .navigationBar)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: onCancel) }
                }
        }
    }
}

private struct BarcodeCamera: UIViewControllerRepresentable {
    var onFound: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let vc = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.ean13])],
                                           qualityLevel: .balanced, isHighlightingEnabled: true)
        vc.delegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: DataScannerViewController, context: Context) {
        context.coordinator.onFound = onFound
        if !vc.isScanning { try? vc.startScanning() }
    }

    static func dismantleUIViewController(_ vc: DataScannerViewController, coordinator: Coordinator) {
        vc.stopScanning()
    }

    func makeCoordinator() -> Coordinator { Coordinator(onFound: onFound) }

    @MainActor
    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        var onFound: (String) -> Void
        private var done = false
        init(onFound: @escaping (String) -> Void) { self.onFound = onFound }

        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem],
                         allItems: [RecognizedItem]) {
            guard !done else { return }
            for item in addedItems {
                guard case .barcode(let code) = item, let value = code.payloadStringValue,
                      value.count == 13, value.hasPrefix("978") || value.hasPrefix("979") else { continue }
                done = true
                dataScanner.stopScanning()
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                onFound(value)
                return
            }
        }
    }
}
