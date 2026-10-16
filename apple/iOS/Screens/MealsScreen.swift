import SwiftUI

/// The Meals tab: the week's plan, or the recipe box.
struct MealsTab: View {
    @SceneStorage("meals.mode") private var mode = "plan"

    var body: some View {
        if mode == "recipes" { RecipesScreen(mode: $mode) } else { MealsScreen(mode: $mode) }
    }
}

/// The week's meals. Narrow: a day per card. Wider: a grid with a column per day. Tap a slot to plan or change it.
struct MealsScreen: View {
    @Environment(AppModel.self) private var model
    @Binding var mode: String
    @State private var anchor: String?
    @State private var meals: [Meal] = []
    @State private var editing: MealSlotEdit?

    struct MealSlotEdit: Identifiable {
        let date: String
        let slot: MealSlot
        let meal: Meal?
        var id: String { "\(date)-\(slot.rawValue)" }
    }

    var body: some View {
        let d = model.dates
        let start = d.weekStart(anchor ?? d.today, start: model.settings?.week_start ?? "monday")
        let days = d.days(from: start, count: 7)
        Page(title: "Meals") { room in
            ScrollView {
                MealsModePicker(mode: $mode).padding(.horizontal, 16).padding(.top, 8)
                if room == .narrow {
                    VStack(spacing: 12) {
                        ForEach(days, id: \.self) { day in dayCard(day) }
                    }
                    .padding(16)
                } else {
                    grid(days: days)
                }
            }
            .refreshable { model.bump("meals") }
        } tools: {
            ToolbarItem(placement: .topBarLeading) {
                DateStepper(label: "This week", onToday: { anchor = nil }) { anchor = d.addDays(start, 7 * $0) }
            }
        }
        .task(id: "\(start)|\(model.rev("meals"))") {
            if let v = await model.call({ try await $0.meals(start, d.addDays(start, 7)) }) { meals = v }
        }
        .sheet(item: $editing) { MealEditor(edit: $0) }
    }

    private func meal(_ day: String, _ slot: MealSlot) -> Meal? {
        meals.first { $0.date == day && $0.slot == slot.rawValue }
    }

    private func dayCard(_ day: String) -> some View {
        let d = model.dates
        let isToday = day == d.today
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(d.relative(day)).font(Theme.text(.headline, .heavy)).foregroundStyle(isToday ? Theme.accent : Theme.text)
                Spacer()
                Text(d.dayMonth(day)).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            }
            ForEach(MealSlot.allCases) { slot in
                let m = meal(day, slot)
                if m != nil || slot == .dinner {
                    slotButton(day, slot, m)
                }
            }
            Menu {
                ForEach(MealSlot.allCases.filter { meal(day, $0) == nil && $0 != .dinner }) { slot in
                    Button("\(slot.emoji) \(slot.label)") { editing = MealSlotEdit(date: day, slot: slot, meal: nil) }
                }
            } label: {
                Label("Add a meal", systemImage: "plus").font(Theme.text(.subheadline, .bold))
            }
        }
        .padding(14)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay { if isToday { RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.accent.opacity(0.6), lineWidth: 2) } }
    }

    private func slotButton(_ day: String, _ slot: MealSlot, _ m: Meal?) -> some View {
        Button { editing = MealSlotEdit(date: day, slot: slot, meal: m) } label: {
            HStack(spacing: 10) {
                Text("\(slot.emoji) \(slot.label)").font(Theme.text(.caption, .bold)).foregroundStyle(Theme.mealText)
                    .frame(width: 96, alignment: .leading)
                Text(m?.title ?? "Plan \(slot.label.lowercased())").font(Theme.text(.subheadline, m == nil ? .semibold : .heavy))
                    .foregroundStyle(m == nil ? Theme.muted : Theme.text).lineLimit(2)
                Spacer()
            }
            .padding(.vertical, 8).padding(.horizontal, 10)
            .background(m == nil ? Theme.surface2 : Theme.mealBg, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private func grid(days: [String]) -> some View {
        let d = model.dates
        return Grid(horizontalSpacing: 8, verticalSpacing: 8) {
            GridRow {
                Color.clear.gridCellUnsizedAxes([.horizontal, .vertical])
                ForEach(days, id: \.self) { day in
                    VStack(spacing: 0) {
                        Text(d.dow(day)).font(Theme.text(.caption2, .heavy)).foregroundStyle(day == d.today ? Theme.accent : Theme.muted)
                        Text(d.dayNum(day)).font(Theme.text(.title3, .heavy)).foregroundStyle(day == d.today ? Theme.accent : Theme.text)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            ForEach(MealSlot.allCases) { slot in
                GridRow {
                    VStack(spacing: 2) {
                        Text(slot.emoji).font(.system(size: 24))
                        Text(slot.label).font(Theme.text(.caption, .heavy))
                    }
                    .frame(width: 72)
                    ForEach(days, id: \.self) { day in
                        let m = meal(day, slot)
                        Button { editing = MealSlotEdit(date: day, slot: slot, meal: m) } label: {
                            Text(m?.title ?? "+")
                                .font(Theme.text(.footnote, m == nil ? .regular : .heavy))
                                .foregroundStyle(m == nil ? Theme.muted : Theme.text)
                                .multilineTextAlignment(.leading)
                                .lineLimit(3)
                                .frame(maxWidth: .infinity, minHeight: 64, alignment: m == nil ? .center : .topLeading)
                                .padding(8)
                                .background(slot == .dinner && m != nil ? Theme.mealBg : Theme.surface,
                                            in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(16)
    }
}

struct MealEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let edit: MealsScreen.MealSlotEdit
    @State private var title = ""
    @State private var notes = ""
    @State private var recipeId: String?
    @State private var recipes: [Recipe] = []
    @State private var askList: Recipe?
    @State private var showAskList = false
    @State private var error: String?

    private var recipe: Recipe? { recipes.first { $0.id == recipeId } }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("What's for \(edit.slot.label.lowercased())?", text: $title).font(Theme.text(.headline))
                    TextField("Notes", text: $notes, axis: .vertical).lineLimit(2...5)
                }
                if !recipes.isEmpty {
                    Section {
                        Picker("Recipe", selection: $recipeId) {
                            Text("None").tag(String?.none)
                            ForEach(recipes) { r in Text("\(r.emoji) \(r.title)").tag(r.id) }
                        }
                        if let recipeId {
                            NavigationLink("Open recipe") { RecipeDetail(id: recipeId) }
                        }
                    }
                    .onChange(of: recipeId) { old, new in
                        let oldTitle = recipes.first { $0.id == old }?.title
                        if let r = recipes.first(where: { $0.id == new }),
                           title.trimmingCharacters(in: .whitespaces).isEmpty || title == oldTitle {
                            title = r.title
                        }
                    }
                }
                if edit.meal != nil {
                    Button("Remove", role: .destructive) {
                        Task {
                            _ = await model.call { try await $0.deleteMeal(edit.meal!.id) }
                            model.bump("meals")
                            dismiss()
                        }
                    }
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle("\(edit.slot.emoji) \(model.dates.relative(edit.date))")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            do {
                                try await model.api?.saveMeal(id: edit.meal?.id, ["date": edit.date, "slot": edit.slot.rawValue,
                                                                                  "title": title.trimmingCharacters(in: .whitespaces), "notes": notes,
                                                                                  "recipe_id": recipeId.map { $0 as Any } ?? NSNull()])
                                model.bump("meals")
                                // A recipe just chosen: offer its ingredients for the shopping list.
                                if let r = recipe, recipeId != edit.meal?.recipe_id, r.ingredients.contains(where: { !$0.heading }) {
                                    askList = r
                                    showAskList = true
                                } else {
                                    dismiss()
                                }
                            } catch { self.error = error.localizedDescription }
                        }
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .navigationDestination(isPresented: $showAskList) {
                if let askList {
                    AddToListView(recipe: askList, title: "Add the ingredients?") { dismiss() }
                        .navigationBarBackButtonHidden()
                }
            }
            .onAppear {
                title = edit.meal?.title ?? ""
                notes = edit.meal?.notes ?? ""
                recipeId = edit.meal?.recipe_id
            }
            .task { recipes = await model.call { try await $0.recipes() } ?? [] }
        }
        .presentationDetents([.medium, .large])
    }
}
