import PhotosUI
import SwiftUI
import UIKit

/// Where a new recipe comes from.
enum RecipeSource: String, Identifiable {
    case scan, photos, link, text
    var id: String { rawValue }
}

/// Bring a recipe in from photos of a cookbook (read on this phone, or by Claude when the add-on has a key), a web
/// page, or pasted text. Hands back an unsaved draft for the editor, where everything can be checked and changed.
struct RecipeImportView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let source: RecipeSource
    var onDraft: (Recipe) -> Void

    @State private var images: [UIImage] = []
    @State private var scanning = false
    @State private var picks: [PhotosPickerItem] = []
    @State private var url = ""
    @State private var text = ""
    @State private var reader: RecipeReader?
    @State private var useClaude = false
    @State private var busy: String?
    @State private var error: String?
    @State private var readText: String?

    var body: some View {
        NavigationStack {
            Form {
                switch source {
                case .scan, .photos: photoSection
                case .link: linkSection
                case .text: textSection
                }
                if let error {
                    Section { Text(error).foregroundStyle(Theme.danger) }
                }
                if let readText, error != nil {
                    Section("What the phone read") {
                        Text(readText).font(.footnote.monospaced()).textSelection(.enabled)
                        Button("Edit this text instead") { switchToText(readText) }
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if let busy {
                        HStack(spacing: 6) { ProgressView(); Text(busy).font(.footnote) }
                    } else {
                        Button("Read recipe") { Task { await run() } }.disabled(!ready)
                    }
                }
            }
            .fullScreenCover(isPresented: $scanning) {
                DocumentScanner { pages in
                    images += pages
                    scanning = false
                } onCancel: {
                    scanning = false
                }
                .ignoresSafeArea()
            }
            .onChange(of: picks) { _, items in
                Task {
                    var out: [UIImage] = []
                    for item in items {
                        if let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data) { out.append(img) }
                    }
                    images = out
                }
            }
            .task {
                reader = await model.call { try await $0.recipeReader() }
                if source == .scan && DocumentScanner.isAvailable && images.isEmpty { scanning = true }
            }
        }
    }

    private var title: String {
        switch source {
        case .scan: "Scan a recipe"
        case .photos: "Recipe from photos"
        case .link: "Recipe from a link"
        case .text: "Paste a recipe"
        }
    }

    private var ready: Bool {
        switch source {
        case .scan, .photos: !images.isEmpty
        case .link: URL(string: url.trimmingCharacters(in: .whitespaces)).map { ["http", "https"].contains($0.scheme ?? "") } ?? false
        case .text: text.trimmingCharacters(in: .whitespacesAndNewlines).count > 10
        }
    }

    private var photoSection: some View {
        Group {
            Section {
                if !images.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 10) {
                            ForEach(images.indices, id: \.self) { i in
                                Image(uiImage: images[i]).resizable().scaledToFill()
                                    .frame(width: 90, height: 120)
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                    .overlay(alignment: .topTrailing) {
                                        Button { images.remove(at: i) } label: {
                                            Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette)
                                                .foregroundStyle(.white, .black.opacity(0.6))
                                        }
                                        .padding(4)
                                    }
                            }
                        }
                    }
                }
                if DocumentScanner.isAvailable {
                    Button { scanning = true } label: {
                        Label(images.isEmpty ? "Scan pages" : "Scan more pages", systemImage: "doc.viewfinder")
                    }
                }
                PhotosPicker(selection: $picks, maxSelectionCount: 6, matching: .images) {
                    Label("Choose photos", systemImage: "photo.on.rectangle")
                }
            } footer: {
                Text("One photo per page, in order. Ingredients and method can be on separate pages.")
            }
            Section {
                if reader?.configured == true {
                    Toggle("Read with Claude", isOn: $useClaude)
                }
            } footer: {
                Text(reader?.configured == true
                     ? (useClaude ? "The photos are sent to Claude, Anthropic's AI, which is better with handwriting and busy layouts."
                                  : "The words are read here on your phone; nothing leaves the house. Turn on Claude for handwriting or busy layouts.")
                     : "The words are read here on your phone. You can check and change everything before it's saved.")
            }
        }
    }

    private var linkSection: some View {
        Section {
            TextField("https://…", text: $url)
                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
        } footer: {
            Text("Most recipe sites mark out the ingredients, steps, times and picture, so they come straight in.")
        }
    }

    private var textSection: some View {
        Group {
            Section {
                TextField("Lemon drizzle cake\nServes 8\nIngredients\n225g butter\n…\nMethod\n1. Heat the oven…", text: $text, axis: .vertical)
                    .lineLimit(8...40)
            } footer: {
                Text("The name on the first line, then the ingredients and the method.")
            }
            if reader?.configured == true {
                Section { Toggle("Read with Claude", isOn: $useClaude) } footer: { Text("Better with messy text.") }
            }
        }
    }

    private func switchToText(_ s: String) {
        dismiss()
        // The editor is the place to fix things: open what was read as a draft with the text as notes.
        let draft = Recipe(id: nil, title: "", emoji: "", description: "", photo: nil, photo_url: nil, rating: 0, favourite: false,
                           servings: nil, prep_minutes: nil, cook_minutes: nil, minutes: nil, ingredients: [], steps: [], tags: [],
                           notes: s, url: nil, cooked_count: 0, last_cooked: nil)
        onDraft(draft)
    }

    private func run() async {
        guard let api = model.api else { return }
        error = nil
        defer { busy = nil }
        do {
            let draft: Recipe
            switch source {
            case .link:
                busy = "Opening the page…"
                draft = try await api.importRecipe(["url": url.trimmingCharacters(in: .whitespaces)])
            case .text:
                busy = useClaude ? "Claude is reading…" : "Reading…"
                draft = try await api.importRecipe(["text": text, "use_reader": useClaude && reader?.configured == true])
            case .scan, .photos:
                if useClaude && reader?.configured == true {
                    busy = "Uploading…"
                    var ids: [String] = []
                    for img in images {
                        guard let jpeg = img.jpeg(max: 2000, quality: 0.9) else { continue }
                        ids.append(try await api.uploadImage(jpeg).id)
                    }
                    busy = "Claude is reading…"
                    draft = try await api.importRecipe(["images": ids])
                } else {
                    busy = "Reading the words…"
                    let words = await TextReader.read(images)
                    readText = words
                    guard !words.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                        error = "No words found in those photos. Try again in better light, with the page flat."
                        return
                    }
                    busy = "Sorting it out…"
                    draft = try await api.importRecipe(["text": words])
                }
            }
            dismiss()
            onDraft(draft)
        } catch {
            self.error = error.localizedDescription
        }
    }
}
