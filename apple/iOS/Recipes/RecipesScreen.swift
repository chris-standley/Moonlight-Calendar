import SwiftUI
import UniformTypeIdentifiers

/// The recipe box: search, quick filters (favourites, quick, tags), sorting, and a card per recipe.
struct RecipesScreen: View {
    @Environment(AppModel.self) private var model
    @State private var recipes: [Recipe] = []
    @State private var loaded = false
    @State private var cookbooks: [Cookbook] = []
    @State private var query = ""
    @State private var filter = "all"
    @AppStorage("recipes.arrange") private var sort = "course"
    @State private var path: [String] = []
    @State private var importing: RecipeSource?
    @State private var draft: Recipe?
    @State private var pendingDraft: Recipe?
    @State private var newRecipe = false
    @State private var batches: [RecipeBatch] = []
    @State private var scanningBook = false
    @State private var checking: RecipeDraft?
    @State private var pickingFile = false
    @State private var exchanging = false
    @State private var exportFile: ExportedFile?
    @State private var exchangeMessage: String?

    var body: some View {
        NavigationStack(path: $path) {
            Adaptive { room, _ in
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(batches) { b in
                            CookbookBatchCard(batch: b) { checking = $0 }
                        }
                        chips
                        if recipes.isEmpty && loaded && batches.isEmpty {
                            EmptyHint(text: "No recipes yet. Tap + to type one in, scan a cookbook or bring one in from a link.")
                        } else if shown.isEmpty && loaded && !recipes.isEmpty {
                            EmptyHint(text: "Nothing matches. Try another word or filter.")
                        }
                        ForEach(groups) { g in
                            if !g.name.isEmpty {
                                groupHeading(g)
                            }
                            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12),
                                                     count: room == .narrow ? 2 : room == .medium ? 3 : 5),
                                      spacing: 12) {
                                ForEach(g.items) { r in
                                    NavigationLink(value: r.id ?? "") { card(r) }.buttonStyle(.plain)
                                }
                            }
                        }
                    }
                    .padding(16)
                }
                .refreshable { model.bump("recipes") }
            }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Recipes")
            .moreTabBar()
            .searchable(text: $query, prompt: "Recipes or ingredients")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Picker("Sort", selection: $sort) {
                            Text("By course").tag("course")
                            Text("By cookbook").tag("book")
                            Text("A to Z").tag("az")
                            Text("Best rated").tag("rated")
                            Text("Recently made").tag("recent")
                        }
                        Divider()
                        Menu {
                            ForEach(RecipeExportFormat.allCases) { f in
                                Button(f.name) { Task { await export(f) } }
                            }
                        } label: { Label("Send to another app", systemImage: "square.and.arrow.up") }
                        .disabled(recipes.isEmpty || exchanging)
                    } label: { Image(systemName: exchanging ? "hourglass" : "arrow.up.arrow.down") }
                    .accessibilityLabel("Sort or send to another app")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button { newRecipe = true } label: { Label("Type it in", systemImage: "square.and.pencil") }
                        if DocumentScanner.isAvailable {
                            Button { importing = .scan } label: { Label("Scan a cookbook page", systemImage: "doc.viewfinder") }
                        }
                        Button { scanningBook = true } label: { Label("Scan a whole cookbook", systemImage: "books.vertical") }
                        Button { importing = .photos } label: { Label("From photos", systemImage: "photo.on.rectangle") }
                        Button { importing = .link } label: { Label("From a link", systemImage: "link") }
                        Button { importing = .text } label: { Label("Paste text", systemImage: "doc.on.clipboard") }
                        Button { pickingFile = true } label: {
                            Label("From another app's file", systemImage: "square.and.arrow.down")
                        }
                        .disabled(exchanging)
                    } label: { Image(systemName: "plus") }
                    .accessibilityLabel("Add a recipe")
                }
            }
            .navigationDestination(for: String.self) { id in RecipeDetail(id: id) }
        }
        .task(id: model.rev("recipes")) {
            if let r = await model.call({ try await $0.recipes() }) { recipes = r }
            if let b = await model.call({ try await $0.recipeBatches() }) { batches = b }
            if let c = await model.call({ try await $0.cookbooks() }) { cookbooks = c }
            loaded = true
        }
        .sheet(item: $importing, onDismiss: {
            draft = pendingDraft
            pendingDraft = nil
        }) { source in
            RecipeImportView(source: source) { pendingDraft = $0 }
        }
        .sheet(item: $draft) { d in
            RecipeEditor(recipe: d) { saved in if let id = saved.id { path = [id] } }
        }
        .sheet(isPresented: $scanningBook) { CookbookScanView() }
        .sheet(item: $checking) { d in
            RecipeEditor(recipe: d.recipe, draftId: d.id)
        }
        .sheet(isPresented: $newRecipe) {
            RecipeEditor { saved in if let id = saved.id { path = [id] } }
        }
        .fileImporter(isPresented: $pickingFile, allowedContentTypes: [.item]) { result in
            if case .success(let url) = result { Task { await importFile(url) } }
        }
        .sheet(item: $exportFile) { f in ShareSheet(items: [f.url]) }
        .alert("Recipes", isPresented: Binding(get: { exchangeMessage != nil }, set: { if !$0 { exchangeMessage = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(exchangeMessage ?? "")
        }
    }

    private func export(_ format: RecipeExportFormat) async {
        guard let api = model.api else { return }
        exchanging = true
        defer { exchanging = false }
        do {
            exportFile = ExportedFile(url: try await api.exportRecipes(format))
        } catch {
            exchangeMessage = error.localizedDescription
        }
    }

    /// Any recipe file: Mela, Paprika, schema.org JSON or a saved web page. The add-on works out which.
    private func importFile(_ url: URL) async {
        guard let api = model.api else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        let file = try? Data(contentsOf: url)
        if scoped { url.stopAccessingSecurityScopedResource() }
        guard let file else {
            exchangeMessage = "Couldn't open that file."
            return
        }
        exchanging = true
        defer { exchanging = false }
        do {
            exchangeMessage = try await api.importRecipes(file).summary
            model.bump("recipes")
        } catch {
            exchangeMessage = error.localizedDescription
        }
    }

    private var tags: [String] {
        var n: [String: Int] = [:]
        for r in recipes { for t in r.tags { n[t, default: 0] += 1 } }
        return n.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.prefix(8).map(\.key)
    }

    private var shown: [Recipe] {
        let words = query.lowercased().split(separator: " ").map(String.init)
        return recipes
            .filter { r in
                let hay = ([r.title, r.description] + r.tags + r.ingredients.map(\.name)).joined(separator: " ").lowercased()
                return words.allSatisfy { hay.contains($0) }
            }
            .filter { r in
                switch filter {
                case "all": true
                case "fav": r.favourite
                case "quick": (r.minutes ?? .max) <= 30
                default: r.tags.contains(filter)
                }
            }
            .sorted { a, b in
                switch sort {
                case "rated": a.rating != b.rating ? a.rating > b.rating : a.title < b.title
                case "recent": (a.last_cooked ?? "") != (b.last_cooked ?? "") ? (a.last_cooked ?? "") > (b.last_cooked ?? "") : a.title < b.title
                default: a.title.localizedCaseInsensitiveCompare(b.title) == .orderedAscending
                }
            }
    }

    /// A group's name and count; a cookbook found by its barcode also shows its cover and author.
    private func groupHeading(_ g: RecipeGroup) -> some View {
        let book = sort == "book" && !g.key.isEmpty ? cookbooks.first(where: { $0.title == g.key }) : nil
        return HStack(alignment: .center, spacing: 10) {
            if let book, book.cover_url != nil {
                RemoteImage(path: book.cover_url)
                    .frame(width: 30, height: 42)
                    .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
            }
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(g.name).font(Theme.text(.title3, .heavy)).foregroundStyle(Theme.text)
                    Text("\(g.items.count)").font(Theme.text(.subheadline, .bold)).foregroundStyle(Theme.muted)
                }
                if let book, !book.byline.isEmpty {
                    Text(book.byline).font(Theme.text(.caption, .semibold)).foregroundStyle(Theme.muted)
                }
            }
        }
        .padding(.top, 6)
    }

    /// By course or by cookbook: a heading per group, in menu order (books A to Z), the rest at the end.
    private var groups: [RecipeGroup] {
        let list = shown
        guard sort == "course" || sort == "book" else { return [RecipeGroup(key: "", name: "", items: list)] }
        let by = Dictionary(grouping: list) { (r: Recipe) -> String in (sort == "course" ? r.course : r.book) ?? "" }
        let order = sort == "course" ? RecipeCourse.all.map(\.key)
            : by.keys.filter { !$0.isEmpty }.sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
        var out: [RecipeGroup] = order.compactMap { k in
            by[k].map { RecipeGroup(key: k, name: sort == "course" ? RecipeCourse.name(k) ?? k : k, items: $0) }
        }
        if let rest = by[""] {
            // Nothing arranged yet: no heading at all.
            let name = out.isEmpty ? "" : sort == "course" ? "No course set" : "Not from a cookbook"
            out.append(RecipeGroup(key: "", name: name, items: rest))
        }
        return out
    }

    private var chips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("fav", "♥ Favourites")
                chip("quick", "30 min or less")
                ForEach(tags, id: \.self) { chip($0, $0) }
            }
        }
    }

    private func chip(_ key: String, _ label: String) -> some View {
        Button { filter = filter == key ? "all" : key } label: {
            Text(label)
                .font(Theme.text(.subheadline, .bold))
                .padding(.horizontal, 14).padding(.vertical, 8)
                .foregroundStyle(filter == key ? .white : Theme.text)
                .background(filter == key ? Theme.accent : Theme.surface, in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private func card(_ r: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            RecipeArt(recipe: r)
                .frame(height: 120)
                .frame(maxWidth: .infinity)
                .overlay(alignment: .topTrailing) {
                    if r.favourite {
                        Image(systemName: "heart.fill").foregroundStyle(Theme.danger)
                            .padding(6).background(.white, in: Circle()).padding(8)
                    }
                }
            VStack(alignment: .leading, spacing: 4) {
                Text(r.title).font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.text).lineLimit(2)
                HStack(spacing: 6) {
                    if r.rating > 0 { Stars(value: r.rating, size: 10) }
                    Text([r.minutes.map { RecipeText.minutes($0) }, r.servings.map { "serves \($0)" }].compactMap { $0 }.joined(separator: " · "))
                        .font(Theme.text(.caption)).foregroundStyle(Theme.muted).lineLimit(1)
                }
            }
            .padding(10)
        }
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: .black.opacity(0.05), radius: 6, y: 2)
    }
}

struct RecipeGroup: Identifiable {
    let key: String
    let name: String
    let items: [Recipe]
    var id: String { key }
}
