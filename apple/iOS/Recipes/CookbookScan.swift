import PhotosUI
import SwiftUI
import UIKit

/// Scan a whole cookbook in one go: the barcode on the back finds the book, then scan or pick the pages, and Claude
/// reads them on Moonlight a few at a time while you carry on. The recipes found turn up at the top of Recipes to check
/// and save, filed under the book.
struct CookbookScanView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    enum Camera: String, Identifiable { case barcode, pages; var id: String { rawValue } }

    @State private var pages: [UIImage] = []
    @State private var camera: Camera?
    @State private var picks: [PhotosPickerItem] = []
    @State private var reader: RecipeReader?
    @State private var uploaded = 0
    @State private var sending = false
    @State private var error: String?
    @State private var cheaper = false
    @State private var book = ""
    @State private var cookbook: Cookbook?
    @State private var isbn = ""
    @State private var findingBook = false
    @State private var bookNote: String?

    static let maxPages = 200

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if !pages.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            LazyHStack(spacing: 8) {
                                ForEach(pages.indices, id: \.self) { i in
                                    Image(uiImage: pages[i]).resizable().scaledToFill()
                                        .frame(width: 60, height: 80)
                                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                        .overlay(alignment: .bottomLeading) {
                                            Text("\(i + 1)").font(.caption2.bold()).padding(3)
                                                .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 4))
                                                .foregroundStyle(.white).padding(3)
                                        }
                                }
                            }
                        }
                        .frame(height: 84)
                        Button("Remove all pages", role: .destructive) { pages = [] }.disabled(sending)
                    }
                    if DocumentScanner.isAvailable {
                        Button { camera = .pages } label: {
                            Label(pages.isEmpty ? "Scan pages" : "Scan more pages", systemImage: "doc.viewfinder")
                        }
                        .disabled(sending)
                    }
                    PhotosPicker(selection: $picks, maxSelectionCount: Self.maxPages, matching: .images) {
                        Label("Choose photos", systemImage: "photo.on.rectangle")
                    }
                    .disabled(sending)
                } header: {
                    Text(pages.isEmpty ? "Pages" : "\(pages.count) \(pages.count == 1 ? "page" : "pages")")
                } footer: {
                    Text("Scan every page you want, in order: the scanner keeps going until you tap Save. Recipes that "
                         + "run over two pages are joined up. Up to \(Self.maxPages) pages at a time.")
                }
                bookSection
                Section {
                    Toggle("Cheaper, slower", isOn: $cheaper).disabled(sending)
                } footer: {
                    Text("Half the price. Anthropic reads the pages when it has room: usually within the hour, at most a day. "
                         + "The recipes all turn up together when it's done.")
                }
                if reader?.configured == false {
                    Section {
                        Text("Reading a whole cookbook needs Claude. Add an Anthropic API key in Moonlight's Settings › Recipes "
                             + "on a wall screen or in Home Assistant.")
                            .foregroundStyle(Theme.danger)
                    }
                }
                if sending {
                    Section {
                        ProgressView(value: Double(uploaded), total: Double(max(pages.count, 1))) {
                            Text("Sending page \(min(uploaded + 1, pages.count)) of \(pages.count)…")
                        }
                    } footer: {
                        Text("Keep the app open until the pages are sent. Reading carries on without it.")
                    }
                }
                if let error {
                    Section { Text(error).foregroundStyle(Theme.danger) }
                }
            }
            .navigationTitle("Scan a cookbook")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Read \(pages.count) \(pages.count == 1 ? "page" : "pages")") { Task { await send() } }
                        .disabled(pages.isEmpty || sending || reader?.configured != true)
                }
            }
            .interactiveDismissDisabled(sending)
            .fullScreenCover(item: $camera) { which in
                switch which {
                case .barcode:
                    BookBarcodeScanner { code in
                        isbn = code
                        Task { await findBook(code) }
                        camera = pages.isEmpty && DocumentScanner.isAvailable ? .pages : nil
                    } onSkip: {
                        camera = DocumentScanner.isAvailable ? .pages : nil
                    } onCancel: {
                        camera = nil
                    }
                case .pages:
                    DocumentScanner { scanned in
                        pages = Array((pages + scanned).prefix(Self.maxPages))
                        camera = nil
                    } onCancel: {
                        camera = nil
                    }
                    .ignoresSafeArea()
                }
            }
            .onChange(of: picks) { _, items in
                guard !items.isEmpty else { return }
                Task {
                    var out: [UIImage] = []
                    for item in items {
                        if let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data) {
                            out.append(img)
                        }
                    }
                    pages = Array((pages + out).prefix(Self.maxPages))
                    picks = []
                }
            }
            .task {
                reader = await model.call { try await $0.recipeReader() }
                // Straight to the camera: the book's barcode first, then its pages.
                if pages.isEmpty && cookbook == nil && reader?.configured == true {
                    camera = BookBarcodeScanner.isAvailable ? .barcode : DocumentScanner.isAvailable ? .pages : nil
                }
            }
        }
    }

    @ViewBuilder private var bookSection: some View {
        Section {
            if let cookbook {
                HStack(spacing: 12) {
                    RemoteImage(path: cookbook.cover_url)
                        .frame(width: 48, height: 68)
                        .background(Theme.muted.opacity(0.2))
                        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(cookbook.title).font(Theme.text(.body, .bold))
                        if !cookbook.byline.isEmpty {
                            Text(cookbook.byline).font(Theme.text(.footnote)).foregroundStyle(Theme.muted)
                        }
                    }
                    Spacer(minLength: 0)
                    Button("Not this book") {
                        self.cookbook = nil
                        book = ""
                        isbn = ""
                    }
                    .font(Theme.text(.footnote, .bold))
                    .buttonStyle(.borderless)
                    .disabled(sending)
                }
                TextField("Name kept with every recipe", text: $book).disabled(sending)
            } else {
                if BookBarcodeScanner.isAvailable {
                    Button { camera = .barcode } label: { Label("Scan the book's barcode", systemImage: "barcode.viewfinder") }
                        .disabled(sending || findingBook)
                }
                HStack {
                    TextField("Or type the ISBN", text: $isbn)
                        .keyboardType(.numbersAndPunctuation)
                        .submitLabel(.search)
                        .onSubmit { Task { await findBook(isbn) } }
                    if findingBook {
                        ProgressView()
                    } else {
                        Button("Find") { Task { await findBook(isbn) } }
                            .buttonStyle(.borderless)
                            .disabled(isbn.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                .disabled(sending)
                TextField("Or just the book's name", text: $book).disabled(sending)
            }
            if let bookNote {
                Text(bookNote).font(Theme.text(.footnote)).foregroundStyle(Theme.danger)
            }
        } header: {
            Text("Which cookbook? (optional)")
        } footer: {
            Text("The barcode on the back finds the book's title, author and cover. Every recipe found is filed under it.")
        }
    }

    private func findBook(_ code: String) async {
        guard let api = model.api, !code.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        findingBook = true
        bookNote = nil
        defer { findingBook = false }
        do {
            let found = try await api.findCookbook(isbn: code)
            cookbook = found
            book = found.title
        } catch {
            bookNote = error.localizedDescription
        }
    }

    private func send() async {
        guard let api = model.api else { return }
        sending = true
        error = nil
        uploaded = 0
        defer { sending = false }
        do {
            var ids: [String] = []
            for page in pages {
                guard let jpeg = page.jpeg(max: 2000, quality: 0.85) else { continue }
                ids.append(try await api.uploadImage(jpeg).id)
                uploaded += 1
            }
            _ = try await api.scanCookbook(images: ids, cheaper: cheaper,
                                           book: book.trimmingCharacters(in: .whitespaces), isbn: cookbook?.isbn)
            model.bump("recipes")
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// A cookbook scan at the top of Recipes: how far the reading has got, pages that couldn't be read, and the recipes
/// found, each to check in the editor (or save all as read).
struct CookbookBatchCard: View {
    @Environment(AppModel.self) private var model
    let batch: RecipeBatch
    var onCheck: (RecipeDraft) -> Void

    @State private var busy = false
    @State private var confirmCancel = false

    var body: some View {
        Card {
            HStack(alignment: .firstTextBaseline) {
                Text("Cookbook scan").font(Theme.text(.title3, .heavy))
                Spacer()
                Menu {
                    if !batch.drafts.isEmpty {
                        Button { act { _ = try await $0.saveAllDrafts(batch.id) } } label: {
                            Label("Save all \(batch.drafts.count) as read", systemImage: "tray.and.arrow.down")
                        }
                    }
                    if !batch.failed.isEmpty {
                        Button { act { _ = try await $0.retryBatch(batch.id) } } label: {
                            Label("Read failed pages again", systemImage: "arrow.clockwise")
                        }
                    }
                    Button(role: .destructive) { confirmCancel = true } label: {
                        Label(batch.reading ? "Stop and clear" : "Clear", systemImage: "xmark")
                    }
                } label: { Image(systemName: "ellipsis.circle").font(.title3) }
                .disabled(busy)
            }
            if batch.reading {
                ProgressView(value: Double(batch.read), total: Double(max(batch.pages, 1))) {
                    Text(progressLine).font(Theme.text(.subheadline, .semibold))
                }
                .tint(Theme.accent)
            }
            if !batch.failed.isEmpty {
                Text(failedLine).font(Theme.text(.footnote, .semibold)).foregroundStyle(Theme.danger)
            }
            if batch.drafts.isEmpty {
                Text(!batch.reading ? "Nothing left to check."
                     : batch.cheaper == true ? "The recipes will appear here when Anthropic sends them back."
                     : "Recipes will appear here as they're read.")
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            } else {
                Text("\(batch.drafts.count) to check" + (batch.saved > 0 ? " · \(batch.saved) saved" : ""))
                    .font(Theme.text(.subheadline, .bold)).foregroundStyle(Theme.muted)
                ForEach(batch.drafts) { d in
                    HStack(spacing: 12) {
                        Button { onCheck(d) } label: {
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(d.recipe.title).font(Theme.text(.body, .bold)).foregroundStyle(Theme.text)
                                    Text(detail(d)).font(Theme.text(.caption)).foregroundStyle(Theme.muted)
                                }
                                Spacer(minLength: 0)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        Button { act { _ = try await $0.saveDraft(d.id) } } label: { Image(systemName: "checkmark.circle") }
                            .accessibilityLabel("Save as read")
                        Button { act { try await $0.dismissDraft(d.id) } } label: { Image(systemName: "trash") }
                            .accessibilityLabel("Don't keep")
                            .foregroundStyle(Theme.muted)
                    }
                    .font(.title3)
                    .disabled(busy)
                    .padding(.vertical, 4)
                }
            }
        }
        .confirmationDialog(batch.reading ? "Stop reading this cookbook?" : "Clear this scan?", isPresented: $confirmCancel,
                            titleVisibility: .visible) {
            Button(batch.reading ? "Stop and clear" : "Clear", role: .destructive) {
                act { try await $0.deleteBatch(batch.id) }
            }
        } message: {
            Text("Recipes already saved stay in the recipe box. The \(batch.drafts.count) not checked yet are dropped.")
        }
    }

    private var progressLine: String {
        if batch.cheaper == true && batch.read < batch.pages {
            return "Cheaper scan: with Anthropic, usually back within the hour (at most a day). "
                + "\(batch.read) of \(batch.pages) pages read."
        }
        return "Claude has read \(batch.read) of \(batch.pages) pages"
    }

    private var failedLine: String {
        let pages = batch.failed.map { "\($0.page)" }.joined(separator: ", ")
        let first = batch.failed.first?.error ?? ""
        return "Couldn't read page\(batch.failed.count == 1 ? "" : "s") \(pages). \(first)"
    }

    private func detail(_ d: RecipeDraft) -> String {
        let page = d.pages.count == 1 ? "Page \(d.pages[0])" : "Pages \(d.pages.first!)–\(d.pages.last!)"
        let i = d.recipe.ingredients.count, s = d.recipe.steps.count
        return "\(page) · \(i) \(i == 1 ? "ingredient" : "ingredients") · \(s) \(s == 1 ? "step" : "steps")"
    }

    private func act(_ work: @escaping (APIClient) async throws -> Void) {
        Task {
            busy = true
            _ = await model.call { try await work($0) }
            model.bump("recipes")
            busy = false
        }
    }
}
