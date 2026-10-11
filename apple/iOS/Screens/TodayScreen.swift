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
    @State private var adding = false

    var body: some View {
        let d = model.dates
        let today = d.today
        Page(title: greeting) { room in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    summaryLine
                    let cols = room.columns(max: 3)
                    let panels: [AnyView] = [AnyView(agenda(today: today)), AnyView(choresCard), AnyView(mealsCard(today: today)), AnyView(groceryCard)]
                    HStack(alignment: .top, spacing: 16) {
                        ForEach(0..<cols, id: \.self) { c in
                            VStack(spacing: 16) {
                                ForEach(Array(panels.enumerated()).filter { $0.offset % cols == c }, id: \.offset) { item in item.element }
                            }
                        }
                    }
                }
                .padding(16)
            }
            .refreshable { await load(today) }
        } tools: {
            ToolbarItem(placement: .primaryAction) {
                Button { adding = true } label: { Image(systemName: "plus") }.accessibilityLabel("New event")
            }
        }
        .task(id: "\(today)|\(model.rev("events", "meals", "chores", "points", "lists"))") { await load(today) }
        .sheet(item: $open) { EventDetailSheet(event: $0) }
        .sheet(isPresented: $adding) { EventEditor() }
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
            if events.isEmpty { EmptyHint(text: "Nothing planned today or tomorrow") }
            ForEach([today, d.addDays(today, 1)], id: \.self) { day in
                let list = events.filter { d.overlaps($0, day: day) }
                    .filter { day != today || $0.all_day || $0.end > d.now }
                    .sorted { ($0.all_day ? 0 : 1, $0.start) < ($1.all_day ? 0 : 1, $1.start) }
                if !list.isEmpty {
                    Text(d.relative(day).uppercased())
                        .font(Theme.text(.caption, .heavy)).kerning(1)
                        .foregroundStyle(day == today ? Theme.accent : Theme.muted)
                    ForEach(list, id: \.key) { ev in
                        Button { open = ev } label: { EventRow(event: ev) }.buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var choresCard: some View {
        Card(title: "Chores today") {
            if model.kids.isEmpty {
                EmptyHint(text: model.people.isEmpty ? "Add your family in Settings › Family." : "Add a child to track their chores and stars.")
            }
            ForEach(model.kids) { kid in
                let mine = chores.filter { $0.person_id == kid.id }
                let done = mine.filter(\.completed).count
                HStack(spacing: 12) {
                    ProgressRing(person: kid, done: done, total: mine.count, size: 48)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(kid.name).font(Theme.text(.headline, .heavy))
                        Text(mine.isEmpty ? "No chores today" : done == mine.count ? "All done! 🎉" : "\(done) of \(mine.count) done")
                            .font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
                    }
                    Spacer()
                    StarBadge(value: points.first { $0.person_id == kid.id }?.balance ?? 0, size: 15)
                }
            }
        }
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
