import SwiftUI

/// Today and tomorrow at a glance. One column on a phone, two when there's room, three on a wide iPad.
struct TodayScreen: View {
    @Environment(AppModel.self) private var model
    @State private var events: [Occurrence] = []
    @State private var meals: [Meal] = []
    @State private var chores: [ChoreDay] = []
    @State private var points: [Balance] = []
    @State private var lists: [TaskList] = []
    @State private var grocery: [ListItem] = []
    @State private var open: Occurrence?
    @State private var adding: Adding?

    /// What the + menu adds: everything Today shows.
    enum Adding: String, Identifiable {
        case event, chore, item, dinner
        var id: String { rawValue }
    }

    var body: some View {
        let d = model.dates
        let today = d.today
        Page(title: greeting) { room in
            let cols = room.columns(max: 3)
            if cols == 1 {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        summaryLine
                        agenda(today: today)
                        choresCard
                        mealsCard(today: today)
                        groceryCard
                    }
                    .padding(16)
                }
                .refreshable { await load(today) }
            } else {
                // Side by side, each column scrolls on its own; the shopping list sits under the meals.
                let groups: [[AnyView]] = cols == 2
                    ? [[AnyView(agenda(today: today))],
                       [AnyView(choresCard), AnyView(mealsCard(today: today)), AnyView(groceryCard)]]
                    : [[AnyView(agenda(today: today))],
                       [AnyView(choresCard)],
                       [AnyView(mealsCard(today: today)), AnyView(groceryCard)]]
                VStack(alignment: .leading, spacing: 0) {
                    summaryLine.padding([.horizontal, .top], 16)
                    HStack(alignment: .top, spacing: 16) {
                        ForEach(groups.indices, id: \.self) { c in
                            ScrollView {
                                VStack(spacing: 16) {
                                    ForEach(groups[c].indices, id: \.self) { groups[c][$0] }
                                }
                                .padding(.vertical, 16)
                            }
                            .scrollIndicators(.hidden)
                            .refreshable { await load(today) }
                        }
                    }
                    .padding(.horizontal, 16)
                }
            }
        } tools: {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button { adding = .event } label: { Label("Event", systemImage: "calendar.badge.plus") }
                    Button { adding = .chore } label: { Label("Chore", systemImage: "checkmark.circle") }
                    Button { adding = .item } label: { Label("List item", systemImage: "cart.badge.plus") }
                    Button { adding = .dinner } label: { Label("Tonight's dinner", systemImage: "fork.knife") }
                } label: {
                    Image(systemName: "plus")
                }
                .accessibilityLabel("Add")
            }
        }
        .task(id: "\(today)|\(model.rev("events", "meals", "chores", "points", "lists"))") { await load(today) }
        .sheet(item: $open) { EventDetailSheet(event: $0) }
        .sheet(item: $adding) { what in
            switch what {
            case .event: EventEditor()
            case .chore: ChoreEditor(chore: nil, personId: model.kids.first?.id ?? model.people.first?.id)
            case .item: ItemAdder(lists: lists)
            case .dinner:
                let today = model.dates.today
                MealEditor(edit: .init(date: today, slot: .dinner,
                                       meal: meals.first { $0.date == today && $0.slot == "dinner" }))
            }
        }
    }

    private var greeting: String {
        let h = model.dates.calendar.component(.hour, from: Date())
        return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"
    }

    private func load(_ today: String) async {
        let d = model.dates
        if let v = await model.call({ try await $0.events(today, d.addDays(today, 2)) }) { events = v }
        if let v = await model.call({ try await $0.meals(today, d.addDays(today, 7)) }) { meals = v }
        if let v = await model.call({ try await $0.chores(today) }) { chores = v }
        if let v = await model.call({ try await $0.points() }) { points = v }
        if let v = await model.call({ try await $0.lists() }) {
            lists = v
            if let g = v.first(where: { $0.kind == "grocery" }), let items = await model.call({ try await $0.items(g.id) }) {
                grocery = items
            }
        }
    }

    private var summaryLine: some View {
        TimelineView(.everyMinute) { ctx in
            HStack(spacing: 10) {
                Text(model.dates.longDate(ctx.date)).font(Theme.text(.headline)).foregroundStyle(Theme.muted)
                if let w = model.weather {
                    WeatherGlyph(condition: w.current.condition, size: 18)
                    Text("\(w.current.temp)°").font(Theme.text(.headline, .heavy)).foregroundStyle(Theme.text)
                }
            }
        }
    }

    private func agenda(today: String) -> some View {
        let d = model.dates
        return Card(title: "Coming up") {
            ForEach([today, d.addDays(today, 1)], id: \.self) { day in
                // Today leaves out what's over, but keeps the whole day's busy line.
                let list = AgendaItem.make(events.filter { d.overlaps($0, day: day) }
                    .filter { day != today || $0.all_day || $0.isBusyBlock || $0.end > d.now }, day: day)
                HStack {
                    Text(d.relative(day).uppercased())
                        .font(Theme.text(.caption, .heavy)).kerning(1)
                        .foregroundStyle(day == today ? Theme.accent : Theme.muted)
                    Spacer()
                    if let w = model.weather?.day(day) { DayWeather(day: w, size: 15) }
                }
                if list.isEmpty { EmptyHint(text: "Nothing planned") }
                ForEach(list) { item in AgendaRow(item: item) { open = $0 } }
            }
        }
    }

    private var choresCard: some View {
        Card(title: "Chores today") {
            if model.kids.isEmpty {
                EmptyHint(text: model.people.isEmpty ? "Add your family in Settings › Family." : "Add a child to track their chores and stars.")
            }
            TimelineView(.everyMinute) { ctx in
                let period = ChoreDay.period(model.dates, at: ctx.date)
                VStack(spacing: 14) {
                    ForEach(model.kids) { kid in kidChores(kid, period: period) }
                }
            }
        }
    }

    /// A child's progress and stars, then up to three chores due now to tick off right here.
    private func kidChores(_ kid: Person, period: String) -> some View {
        let mine = chores.filter { $0.person_id == kid.id }
        let done = mine.filter(\.completed).count
        let due = ChoreDay.dueNow(mine, period: period)
        let later = mine.first { !$0.completed && !due.contains($0) }
        let status = mine.isEmpty ? "No chores today" : done == mine.count ? "All \(done) done 🎉"
            : !due.isEmpty ? "\(done) of \(mine.count) done"
            : "\(done) of \(mine.count) done · later: \(later.map { "\($0.emoji) \($0.title)" } ?? "")"
        let color = Color(hex: kid.color)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                ProgressRing(person: kid, done: done, total: mine.count, size: 48)
                VStack(alignment: .leading, spacing: 2) {
                    Text(kid.name).font(Theme.text(.headline, .heavy))
                    Text(status).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted).lineLimit(1)
                }
                Spacer()
                StarBadge(value: points.first { $0.person_id == kid.id }?.balance ?? 0, size: 15)
            }
            ForEach(due.prefix(3)) { c in
                Button { Task { await tick(c) } } label: {
                    HStack(spacing: 10) {
                        Text(c.emoji).font(.title3)
                        Text(c.title).font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                        Spacer(minLength: 4)
                        Circle().strokeBorder(color, lineWidth: 2).frame(width: 26, height: 26)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Done: \(c.title)")
            }
            if due.count > 3 {
                Text("+\(due.count - 3) more").font(Theme.text(.caption, .heavy)).foregroundStyle(Theme.muted).padding(.leading, 4)
            }
        }
        .padding(10)
        .background(color.opacity(0.1), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func tick(_ c: ChoreDay) async {
        let today = model.dates.today
        if let i = chores.firstIndex(of: c) { chores[i].completed = true }  // straight away; the reload confirms it
        _ = await model.call { try await $0.setChore(c.id, date: today, done: true) }
        model.bump("chores")
        model.bump("points")
    }

    private func mealsCard(today: String) -> some View {
        let d = model.dates
        return Card(title: "Meals") {
            if !meals.contains(where: { $0.date == today }) { EmptyHint(text: "Nothing planned today") }
            ForEach(MealSlot.allCases) { slot in
                if let meal = meals.first(where: { $0.date == today && $0.slot == slot.rawValue }) {
                    HStack {
                        Text("\(slot.emoji) \(slot.label)").font(Theme.text(.caption, .bold)).foregroundStyle(Theme.mealText).frame(width: 96, alignment: .leading)
                        Text(meal.title).font(Theme.text(.subheadline, .heavy)).lineLimit(1)
                        Spacer()
                    }
                    .padding(.vertical, 6).padding(.horizontal, 10)
                    .background(Theme.mealBg, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
            }
            Divider()
            ForEach(1..<6, id: \.self) { i in
                let day = d.addDays(today, i)
                HStack {
                    Text(d.dow(day)).font(Theme.text(.caption, .heavy)).foregroundStyle(Theme.muted).frame(width: 44, alignment: .leading)
                    Text(meals.first { $0.date == day && $0.slot == "dinner" }?.title ?? "—").font(Theme.text(.subheadline)).lineLimit(1)
                }
            }
        }
    }

    private var groceryCard: some View {
        let list = lists.first { $0.kind == "grocery" }
        let open = grocery.filter { !$0.done }
        return Card(title: list.map { "\($0.emoji) \($0.name)" } ?? "Shopping") {
            if open.isEmpty { EmptyHint(text: list == nil ? "No shopping list yet" : "All bought") }
            ForEach(open.prefix(8)) { item in
                Label(item.title, systemImage: "circle").font(Theme.text(.subheadline, .semibold))
            }
            if open.count > 8 { Text("+ \(open.count - 8) more").font(Theme.text(.caption)).foregroundStyle(Theme.muted) }
        }
    }
}

/// Add one or more items ("milk, eggs and bread") to a list, the shopping list first.
struct ItemAdder: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let lists: [TaskList]
    @State private var listId = ""
    @State private var text = ""
    @State private var error: String?
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            Form {
                if lists.isEmpty {
                    Text("Make a list on the Lists tab first.").foregroundStyle(Theme.muted)
                } else {
                    Section {
                        TextField("Milk, eggs and bread", text: $text).font(Theme.text(.headline))
                            .focused($focused).submitLabel(.done).onSubmit { Task { await save() } }
                        Picker("List", selection: $listId) {
                            ForEach(lists) { Text("\($0.emoji) \($0.name)").tag($0.id) }
                        }
                    } footer: {
                        Text("Separate several with commas.")
                    }
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle("Add to a list")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") { Task { await save() } }.disabled(parts.isEmpty || listId.isEmpty)
                }
            }
            .onAppear {
                listId = (lists.first { $0.kind == "grocery" } ?? lists.first)?.id ?? ""
                focused = true
            }
        }
        .presentationDetents([.medium])
    }

    private var parts: [String] {
        text.replacingOccurrences(of: " and ", with: ",").split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private func save() async {
        guard let api = model.api, !parts.isEmpty, !listId.isEmpty else { return }
        do {
            for p in parts { try await api.addItem(listId, title: p) }
            model.bump("lists")
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
