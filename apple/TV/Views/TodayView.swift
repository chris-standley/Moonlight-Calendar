import SwiftUI

/// Home: today and tomorrow, meals, the children's chores and what's playing.
private struct SlotMeal {
    let slot: MealSlot
    let meal: Meal
}

struct TodayView: View {
    @Environment(AppModel.self) private var model
    @State private var events: [Occurrence] = []
    @State private var meals: [Meal] = []
    @State private var chores: [ChoreDay] = []
    @State private var points: [Balance] = []
    @State private var open: Occurrence?

    var body: some View {
        let d = model.dates
        let today = d.today
        Screen {
            HStack(alignment: .top, spacing: 36) {
                agenda(today: today)
                    .frame(maxWidth: .infinity)
                VStack(spacing: 36) {
                    mealsPanel(today: today)
                    NowPlayingCard()
                }
                .frame(width: 520)
                choresPanel
                    .frame(width: 560)
            }
        }
        .task(id: "\(today)|\(model.rev("events", "meals", "chores", "points"))") {
            if let v = await model.call({ try await $0.events(today, d.addDays(today, 2)) }) { events = v }
            if let v = await model.call({ try await $0.meals(today, d.addDays(today, 7)) }) { meals = v }
            if let v = await model.call({ try await $0.chores(today) }) { chores = v }
            if let v = await model.call({ try await $0.points() }) { points = v }
        }
        .sheet(item: $open) { EventDetail(event: $0) }
    }

    private func agenda(today: String) -> some View {
        let d = model.dates
        return VStack(alignment: .leading, spacing: 16) {
            Text("Coming up").font(Theme.font(34, .heavy)).foregroundStyle(Theme.text)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if events.isEmpty {
                        EmptyNote(text: "Nothing planned today or tomorrow")
                    }
                    ForEach([today, d.addDays(today, 1)], id: \.self) { day in
                        let dayEvents = AgendaItem.make(events.filter { d.overlaps($0, day: day) }
                            .filter { day != today || $0.all_day || $0.isBusyBlock || $0.end > d.now }, day: day)
                        if !dayEvents.isEmpty {
                            Text(d.relative(day).uppercased())
                                .font(Theme.font(22, .heavy)).kerning(1.5)
                                .foregroundStyle(day == today ? Theme.accent : Theme.muted)
                                .padding(.top, 8)
                            ForEach(dayEvents) { item in AgendaCard(item: item) { open = $0 } }
                        }
                    }
                }
                .padding(20)
            }
            .scrollClipDisabled()
        }
        .panel(padding: 24)
    }

    private func mealsPanel(today: String) -> some View {
        let d = model.dates
        let todays = MealSlot.allCases.compactMap { slot in meals.first { $0.date == today && $0.slot == slot.rawValue }.map { SlotMeal(slot: slot, meal: $0) } }
        return VStack(alignment: .leading, spacing: 14) {
            Text("Today's meals").font(Theme.font(34, .heavy)).foregroundStyle(Theme.text)
            if todays.isEmpty { Text("Nothing planned yet").font(Theme.font(24, .bold)).foregroundStyle(Theme.muted) }
            ForEach(todays, id: \.meal.id) { item in
                let slot = item.slot
                let meal = item.meal
                HStack(spacing: 14) {
                    Text("\(slot.emoji) \(slot.label)").font(Theme.font(22, .bold)).foregroundStyle(Theme.mealText)
                        .frame(width: 180, alignment: .leading)
                    Text(meal.title).font(Theme.font(26, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                }
                .padding(.vertical, 10).padding(.horizontal, 16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.mealBg, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            Divider().padding(.vertical, 4)
            ForEach(1..<6, id: \.self) { i in
                let day = d.addDays(today, i)
                HStack {
                    Text(d.dow(day)).font(Theme.font(20, .heavy)).foregroundStyle(Theme.muted).frame(width: 70, alignment: .leading)
                    Text(meals.first { $0.date == day && $0.slot == "dinner" }?.title ?? "—")
                        .font(Theme.font(23, .bold)).foregroundStyle(Theme.text).lineLimit(1)
                    Spacer()
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .panel(padding: 28)
    }

    private var choresPanel: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Chores today").font(Theme.font(34, .heavy)).foregroundStyle(Theme.text)
            if model.kids.isEmpty {
                Text(model.people.isEmpty ? "Add your family in Settings › Family." : "Add a child in Settings › Family to track their chores and stars.")
                    .font(Theme.font(24, .bold)).foregroundStyle(Theme.muted)
            }
            ScrollView {
                VStack(spacing: 20) {
                    ForEach(model.kids) { kid in kidChores(kid, period: ChoreDay.period(model.dates)) }
                }
                .padding(8)
            }
            .scrollClipDisabled()
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .panel(padding: 28)
    }

    /// Progress and stars, then the chores due now (up to three): select one to tick it off.
    private func kidChores(_ kid: Person, period: String) -> some View {
        let mine = chores.filter { $0.person_id == kid.id }
        let done = mine.filter(\.completed).count
        let due = ChoreDay.dueNow(mine, period: period)
        let later = mine.first { !$0.completed && !due.contains($0) }
        let color = Color(hex: kid.color)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 20) {
                ProgressRing(person: kid, done: done, total: mine.count, size: 90)
                VStack(alignment: .leading, spacing: 4) {
                    Text(kid.name).font(Theme.font(30, .heavy)).foregroundStyle(Theme.text)
                    Text(mine.isEmpty ? "No chores today" : done == mine.count ? "All \(done) done 🎉" : "\(done) of \(mine.count) done")
                        .font(Theme.font(22, .bold)).foregroundStyle(done == mine.count && !mine.isEmpty ? color : Theme.muted)
                    if due.isEmpty, let later {
                        Text("Later: \(later.emoji) \(later.title)").font(Theme.font(21, .semibold)).foregroundStyle(Theme.muted).lineLimit(1)
                    }
                }
                Spacer()
                StarBadge(value: points.first { $0.person_id == kid.id }?.balance ?? 0, size: 24)
            }
            ForEach(due.prefix(3)) { c in
                Button { Task { await tick(c) } } label: {
                    HStack(spacing: 14) {
                        Text(c.emoji).font(.system(size: 30))
                        Text(c.title).font(Theme.font(24, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                        Spacer(minLength: 6)
                        Circle().strokeBorder(color, lineWidth: 3).frame(width: 38, height: 38)
                    }
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .buttonStyle(.moonCard(radius: 14, ring: color))
            }
            if due.count > 3 {
                Text("+\(due.count - 3) more on Chores").font(Theme.font(19, .heavy)).foregroundStyle(Theme.muted)
            }
        }
        .padding(18)
        .background(color.opacity(0.1), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private func tick(_ c: ChoreDay) async {
        let today = model.dates.today
        if let i = chores.firstIndex(of: c) { chores[i].completed = true }
        _ = await model.call { try await $0.setChore(c.id, date: today, done: true) }
        model.bump("chores")
        model.bump("points")
    }
}
