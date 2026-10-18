import SwiftUI
import UIKit

/// The recipe box to and from other recipe apps: Mela (.melarecipes), Paprika (.paprikarecipes) and schema.org Recipe
/// JSON. Moonlight works out what kind of file it's been given, so importing never asks.
enum RecipeExportFormat: String, CaseIterable, Identifiable {
    case mela, paprika, schema
    var id: String { rawValue }
    var name: String {
        switch self {
        case .mela: "Mela"
        case .paprika: "Paprika"
        case .schema: "schema.org JSON"
        }
    }
    var fileExtension: String {
        switch self {
        case .mela: "melarecipes"
        case .paprika: "paprikarecipes"
        case .schema: "json"
        }
    }
}

struct RecipeImportResult: Decodable {
    let added: Int
    let skipped: [String]
    let failed: [String]

    var summary: String {
        var parts = ["\(added) \(added == 1 ? "recipe" : "recipes") added."]
        if !skipped.isEmpty { parts.append("\(skipped.count) already in the recipe box, so left alone.") }
        if !failed.isEmpty { parts.append("Couldn't bring in: \(failed.joined(separator: ", ")).") }
        return parts.joined(separator: " ")
    }
}

extension APIClient {
    /// The whole recipe box, pictures included, written to a temporary file ready to share.
    func exportRecipes(_ format: RecipeExportFormat) async throws -> URL {
        var req = request(url("/api/recipes/export", query: ["format": format.rawValue]))
        req.timeoutInterval = 300
        let body = try await data(for: req)
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("Moonlight recipes.\(format.fileExtension)")
        try body.write(to: file, options: .atomic)
        return file
    }

    /// A recipe file from another app, any kind Moonlight reads; the recipes are saved straight into the box.
    func importRecipes(_ file: Data) async throws -> RecipeImportResult {
        var req = request(url("/api/recipes/collection"), method: "POST")
        req.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        req.httpBody = file
        req.timeoutInterval = 600
        return try JSONDecoder().decode(RecipeImportResult.self, from: try await data(for: req))
    }
}

struct ExportedFile: Identifiable {
    let url: URL
    var id: URL { url }
}

/// The system share sheet, so an export can go straight to Mela or Paprika, Files, AirDrop or Mail.
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
