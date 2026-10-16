import SwiftUI

/// Pick which ingredients go on a list. Opened from a recipe ("Add to list") and after planning a meal with one.
/// Everyday staples and things already waiting on the list start unticked.
struct AddToListView: View {
    @Environment(AppModel.self) private var model
    let recipe: Recipe
    var title: String? = nil
    var onDone: () -> Void

    @State private var lists: [TaskList] = []
    @State private var listId: String?
    @State private var items: [ListItem] = []
    @State private var servings: Double = 1
    @State private var picked: Set<Int> = []
    @State private var busy = false
    @State private var error: String?

    private static let staples: Set<String> = ["salt", "pepper", "black pepper", "salt and pepper", "salt & pepper",
                                               "sea salt", "water", "cold water", "boiling water", "warm water", "oil",
                                               "olive oil", "vegetable oil", "sunflower oil", "cooking spray", "ice"]

    private var factor: Double { recipe.factor(servings) }
    private var rows: [Int] { recipe.ingredients.indices.filter { !recipe.ingredients[$0].heading } }

    static func isStaple(_ ing: Ingredient) -> Bool {
        staples.contains(ing.name.trimmingCharacters(in: .whitespaces).lowercased())
    }

    private func onList(_ ing: Ingredient) -> Bool {
        var n = ing.name.lowercased()
        if n.hasSuffix("s") { n.removeLast() }
        return n.count >= 3 && items.contains { !$0.done && $0.title.lowercased().contains(n) }
    }

    var body: some View {
        List {
            Section {
                if lists.count > 1 {
                    Picker("List", selection: $listId) {
                        ForEach(lists) { Text("\($0.emoji) \($0.name)").tag(Optional($0.id)) }
                    }
                }
                HStack {
                    Text("Make").foregroundStyle(Theme.muted)
                    Spacer()
                    ServingsStepper(recipe: recipe, servings: $servings)
                }
            }
            Section {
                ForEach(recipe.ingredients.indices, id: \.self) { i in
                    let ing = recipe.ingredients[i]
                    if ing.heading {
                        Text(ing.name).font(Theme.text(.caption, .heavy)).foregroundStyle(Theme.muted)
                    } else {
                        Button {
                            if picked.contains(i) { picked.remove(i) } else { picked.insert(i) }
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: picked.contains(i) ? "checkmark.circle.fill" : "circle")
                                    .font(.title3)
                                    .foregroundStyle(picked.contains(i) ? Theme.accent : Theme.muted)
                                IngredientLine(ing: ing, factor: factor).opacity(picked.contains(i) ? 1 : 0.55)
                                Spacer()
                                if onList(ing) {
                                    Text("On the list").font(Theme.text(.caption, .bold)).foregroundStyle(Theme.muted)
                                } else if Self.isStaple(ing) {
                                    Text("Usually in").font(Theme.text(.caption, .bold)).foregroundStyle(Theme.muted)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            } footer: {
                HStack {
                    Button("All") { picked = Set(rows) }
                    Button("None") { picked = [] }
                }
                .font(Theme.text(.subheadline, .bold))
            }
            if let error { Text(error).foregroundStyle(Theme.danger) }
        }
        .navigationTitle(title ?? "Add to a list")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button(title == nil ? "Cancel" : "Skip") { onDone() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Add \(picked.count)") { Task { await add() } }
                    .disabled(picked.isEmpty || listId == nil || busy)
            }
        }
        .task {
            servings = recipe.defaultServings
            guard let all = await model.call({ try await $0.lists() }) else { return }
            lists = all.sorted { ($0.kind == "grocery" ? 0 : 1, $0.sort) < ($1.kind == "grocery" ? 0 : 1, $1.sort) }
            if listId == nil { listId = lists.first?.id }
            if lists.isEmpty { error = "There are no lists yet. Make a shopping list in Lists first." }
        }
        .task(id: listId) {
            guard let listId else { return }
            items = await model.call({ try await $0.items(listId) }) ?? []
            picked = Set(rows.filter { !Self.isStaple(recipe.ingredients[$0]) && !onList(recipe.ingredients[$0]) })
        }
    }

    private func add() async {
        guard let listId, let id = recipe.id else { return }
        busy = true
        defer { busy = false }
        let lines = rows.filter(picked.contains).map { RecipeText.shopping(recipe.ingredients[$0], factor) }
        do {
            _ = try await model.api?.recipeToList(id, listId: listId, items: lines)
            model.bump("lists")
            onDone()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Put a recipe on the meal plan, then offer its ingredients for the shopping list.
struct PlanRecipeView: View {
    @Environment(AppModel.self) private var model
    let recipe: Recipe
    var onDone: () -> Void

    @State private var day = Date()
    @State private var slot: MealSlot = .dinner
    @State private var planned = false
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                Picker("Meal", selection: $slot) {
                    ForEach(MealSlot.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                DatePicker("Day", selection: $day, in: Calendar.current.startOfDay(for: Date())..., displayedComponents: .date)
                    .datePickerStyle(.graphical)
            }
            if let error { Text(error).foregroundStyle(Theme.danger) }
        }
        .navigationTitle("Plan \(recipe.title)")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { onDone() } }
            ToolbarItem(placement: .confirmationAction) { Button("Plan it") { Task { await plan() } } }
        }
        .navigationDestination(isPresented: $planned) {
            AddToListView(recipe: recipe, title: "Add the ingredients?", onDone: onDone)
        }
    }

    private func plan() async {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        do {
            try await model.api?.saveMeal(id: nil, ["date": f.string(from: day), "slot": slot.rawValue, "title": recipe.title,
                                                    "notes": "", "recipe_id": recipe.id.map { $0 as Any } ?? NSNull()])
            model.bump("meals")
            if recipe.ingredients.contains(where: { !$0.heading }) { planned = true } else { onDone() }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
