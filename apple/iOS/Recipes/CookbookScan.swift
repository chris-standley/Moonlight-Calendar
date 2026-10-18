import PhotosUI
import SwiftUI
import UIKit

/// Scan a whole cookbook in one go: scan or pick the pages, and Claude reads them on Moonlight a few at a time while
/// you carry on. The recipes found turn up at the top of Recipes to check and save.
struct CookbookScanView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    @State private var pages: [UIImage] = []
    @State private var scanning = false
    @State private var picks: [PhotosPickerItem] = []
    @State private var reader: RecipeReader?
    @State private var uploaded = 0
    @State private var sending = false
    @State private var error: String?

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
                        Button { scanning = true } label: {
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
            .fullScreenCover(isPresented: $scanning) {
                DocumentScanner { scanned in
                    pages = Array((pages + scanned).prefix(Self.maxPages))
                    scanning = false
                } onCancel: {
                    scanning = false
                }
                .ignoresSafeArea()
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
                if DocumentScanner.isAvailable && pages.isEmpty && reader?.configured == true { scanning = true }
            }
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
            _ = try await api.scanCookbook(images: ids)
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
                    Text("Claude has read \(batch.read) of \(batch.pages) pages").font(Theme.text(.subheadline, .semibold))
                }
                .tint(Theme.accent)
            }
            if !batch.failed.isEmpty {
                Text(failedLine).font(Theme.text(.footnote, .semibold)).foregroundStyle(Theme.danger)
            }
            if batch.drafts.isEmpty {
                Text(batch.reading ? "Recipes will appear here as they're read." : "Nothing left to check.")
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
