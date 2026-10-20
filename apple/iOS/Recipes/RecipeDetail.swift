import SwiftUI

/// A recipe: picture, rating, scaling, ingredients (with metric beside cups and ounces), the method with its timers,
/// and what to do with it: cook it, add it to a list, plan it.
struct RecipeDetail: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let id: String

    @State private var recipe: Recipe?
    @State private var servings: Double = 1
    @State private var sheet: Sheet?
    @State private var cooking = false
    private var timers: KitchenTimers { KitchenTimers.shared }

    enum Sheet: String, Identifiable {
        case edit, list, plan
        var id: String { rawValue }
    }

    var body: some View {
        Adaptive { room, _ in
            if let r = recipe {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if room == .narrow {
                            RecipeArt(recipe: r, emojiSize: 80).frame(height: 240).clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                            intro(r)
                            ingredients(r)
                            method(r)
                        } else {
                            HStack(alignment: .top, spacing: 20) {
                                RecipeArt(recipe: r, emojiSize: 100).frame(height: 300).frame(maxWidth: .infinity)
                                    .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                                intro(r).frame(maxWidth: .infinity, alignment: .leading)
                            }
                            HStack(alignment: .top, spacing: 20) {
                                ingredients(r).frame(maxWidth: .infinity)
                                method(r).frame(maxWidth: .infinity)
                            }
                        }
                    }
                    .padding(16)
                }
                .safeAreaInset(edge: .bottom) { TimerTray(timers: timers) }
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Theme.bg.ignoresSafeArea())
        .navigationTitle(recipe?.title ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) { Button("Edit") { sheet = .edit }.disabled(recipe == nil) }
        }
        .task(id: model.rev("recipes")) {
            guard let r = await model.call({ try await $0.recipe(id) }) else { return }
            if recipe == nil { servings = r.defaultServings }
            recipe = r
        }
        .sheet(item: $sheet) { which in
            if let r = recipe {
                switch which {
                case .edit:
                    RecipeEditor(recipe: r) { _ in }
                case .list:
                    NavigationStack { AddToListView(recipe: r) { sheet = nil } }
                case .plan:
                    NavigationStack { PlanRecipeView(recipe: r) { sheet = nil } }
                }
            }
        }
        .fullScreenCover(isPresented: $cooking) {
            if let r = recipe { CookView(recipe: r, factor: r.factor(servings)) }
        }
    }

    private func intro(_ r: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(r.title).font(Theme.text(.title, .heavy)).foregroundStyle(Theme.text)
            HStack(spacing: 14) {
                Stars(value: r.rating, size: 22) { n in Task { await patch(["rating": n]) } }
                Button { Task { await patch(["favourite": !r.favourite]) } } label: {
                    Image(systemName: r.favourite ? "heart.fill" : "heart").font(.title2)
                        .foregroundStyle(r.favourite ? Theme.danger : Theme.muted)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(r.favourite ? "Favourite" : "Not a favourite")
            }
            if !r.description.isEmpty {
                Text(r.description).font(Theme.text(.body, .regular)).foregroundStyle(Theme.text)
            }
            TimeFacts(recipe: r)
            Text(madeLine(r)).font(Theme.text(.footnote, .semibold)).foregroundStyle(Theme.muted)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) { actions(r) }
                VStack(alignment: .leading, spacing: 10) { actions(r) }
            }
            if let link = r.url, let url = URL(string: link) {
                Link(destination: url) { Label("Original recipe", systemImage: "safari") }
                    .font(Theme.text(.subheadline, .bold))
            }
        }
    }

    @ViewBuilder
    private func actions(_ r: Recipe) -> some View {
        Button { cooking = true } label: { Label("Start cooking", systemImage: "play.fill") }
            .buttonStyle(.borderedProminent)
            .disabled(r.steps.isEmpty)
        Button { sheet = .list } label: { Label("Add to list", systemImage: "cart") }
            .buttonStyle(.bordered)
            .disabled(r.ingredients.isEmpty)
        Button { sheet = .plan } label: { Label("Plan it", systemImage: "calendar") }
            .buttonStyle(.bordered)
    }

    private func ingredients(_ r: Recipe) -> some View {
        Card {
            HStack {
                Text("Ingredients").font(Theme.text(.title3, .heavy))
                Spacer()
                ServingsStepper(recipe: r, servings: $servings)
            }
            if r.factor(servings) != 1 {
                HStack(spacing: 4) {
                    Text(r.servings.map { "Scaled from \($0) servings." } ?? "Scaled.")
                    Button("Reset") { servings = r.defaultServings }
                }
                .font(Theme.text(.footnote, .semibold)).foregroundStyle(Theme.muted)
            }
            if r.ingredients.isEmpty {
                EmptyHint(text: "No ingredients yet.")
            }
            ForEach(r.ingredients.indices, id: \.self) { i in
                IngredientLine(ing: r.ingredients[i], factor: r.factor(servings))
            }
        }
    }

    private func method(_ r: Recipe) -> some View {
        Card(title: "Method") {
            if r.steps.isEmpty { EmptyHint(text: "No steps yet. Tap Edit to add them.") }
            ForEach(r.steps.indices, id: \.self) { i in
                let s = r.steps[i]
                HStack(alignment: .top, spacing: 12) {
                    Text("\(i + 1)").font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.accent)
                        .frame(width: 30, height: 30).background(Theme.accent.opacity(0.12), in: Circle())
                    VStack(alignment: .leading, spacing: 8) {
                        Text(s.shown).font(Theme.text(.body, .medium)).foregroundStyle(Theme.text)
                        StepAmounts(recipe: r, step: s, factor: r.factor(servings))
                        if s.photo_url != nil {
                            RemoteImage(path: s.photo_url).frame(height: 160).frame(maxWidth: .infinity)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        if !s.timers.isEmpty {
                            HStack {
                                ForEach(s.timers, id: \.seconds) { t in
                                    Button { timers.start("Step \(i + 1): \(t.label)", seconds: t.seconds, recipe: r.title) } label: {
                                        Label(t.label, systemImage: "timer").font(Theme.text(.caption, .heavy))
                                    }
                                    .buttonStyle(.bordered)
                                    .controlSize(.small)
                                }
                            }
                        }
                    }
                }
            }
            if !r.notes.isEmpty {
                Text("Notes").font(Theme.text(.headline, .heavy)).padding(.top, 6)
                Text(r.notes).font(Theme.text(.body, .regular)).foregroundStyle(Theme.text)
            }
        }
    }

    private func madeLine(_ r: Recipe) -> String {
        var parts: [String] = []
        if r.cooked_count > 0, let last = r.last_cooked {
            let d = model.dates
            let when = last == d.today ? "today" : last == d.addDays(d.today, -1) ? "yesterday" : "on \(d.dayMonth(last))"
            parts.append("Made \(r.cooked_count) \(r.cooked_count == 1 ? "time" : "times"), last \(when)")
        } else {
            parts.append("Not made yet")
        }
        if !r.tags.isEmpty { parts.append(r.tags.joined(separator: ", ")) }
        if let c = RecipeCourse.name(r.course) { parts.append(c) }
        if let b = RecipeCourse.bookLine(r.book, r.book_page) { parts.append(b) }
        return parts.joined(separator: " · ")
    }

    private func patch(_ body: [String: Any]) async {
        if let r = await model.call({ try await $0.saveRecipe(id: id, body) }) { recipe = r }
        model.bump("recipes")
    }
}
