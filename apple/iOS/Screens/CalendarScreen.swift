import SwiftUI

/// Day (with a week strip), Week grid and Schedule. Narrow screens open on Day, wider ones on Week;
/// the Week grid needs at least a medium width, so a phone folding shut falls back to Day.
struct CalendarScreen: View {
    enum Mode: String, CaseIterable, Identifiable {
        case day = "Day", week = "Week", schedule = "Schedule"
        var id: String { rawValue }
    }

    @Environment(AppModel.self) private var model
    @State private var chosen: Mode?
    @State private var selected: String?
    @State private var hidden: Set<String> = []
    @State private var events: [Occurrence] = []
    @State private var meals: [Meal] = []
    @State private var open: Occurrence?
    @State private var adding: String?
    @State private var room: Room = .narrow

    var body: some View {
        let d = model.dates
        let day = selected ?? d.today
        let mode = effectiveMode
        let start = mode == .schedule ? day : d.weekStart(day, start: model.settings?.week_start ?? "monday")
        let count = mode == .schedule ? 21 : 7
        let days = d.days(from: start, count: count)
        let visible = events.filter { ev in ev.person_ids.isEmpty || ev.person_ids.contains { !hidden.contains($0) } }

        Page(title: title(mode: mode, days: days, day: day)) { room in
            VStack(spacing: 12) {
                controls(room: room)
                switch mode {
                case .day: dayView(days: days, day: day, events: visible)
                case .week: weekView(days: days, events: visible)
                case .schedule: scheduleView(days: days, events: visible)
                }
            }
            .onAppear { self.room = room }
            .onChange(of: room) { self.room = room }
        } tools: {
            ToolbarItem(placement: .topBarLeading) {
                DateStepper(label: "Today", onToday: { selected = nil }) { step in
                    selected = d.addDays(day, step * (mode == .day ? 1 : mode == .week ? 7 : 21))
                }
            }
            ToolbarItem(placement: .primaryAction) {
                Button { adding = day } label: { Image(systemName: "plus") }.accessibilityLabel("New event")
            }
        }
        .task(id: "\(days.first!)|\(days.last!)|\(model.rev("events", "meals"))") {
            let end = d.addDays(days.last!, 1)
            if let v = await model.call({ try await $0.events(days.first!, end) }) { events = v }
            if let v = await model.call({ try await $0.meals(days.first!, end) }) { meals = v }
        }
        .sheet(item: $open) { EventDetailSheet(event: $0) }
        .sheet(item: Binding(get: { adding.map(DayID.init) }, set: { adding = $0?.id })) { EventEditor(day: $0.id) }
    }

    private struct DayID: Identifiable { let id: String }

    private var effectiveMode: Mode {
        let m = chosen ?? (room == .narrow ? .day : .week)
        return m == .week && room == .narrow ? .day : m
    }

    private func title(mode: Mode, days: [String], day: String) -> String {
        let d = model.dates
        switch mode {
        case .day: return d.relative(day)
        case .week, .schedule: return "\(d.dayMonth(days.first!)) – \(d.dayMonth(days.last!))"
        }
    }

    private func controls(room: Room) -> some View {
        let modes = room == .narrow ? [Mode.day, .schedule] : Mode.allCases
        return ViewThatFits(in: .horizontal) {
            HStack {
                picker(modes).frame(maxWidth: 320)
                Spacer()
                PeopleFilter(hidden: $hidden)
            }
            VStack(spacing: 10) {
                picker(modes)
                PeopleFilter(hidden: $hidden, size: 32)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
    }

    private func picker(_ modes: [Mode]) -> some View {
        Picker("View", selection: Binding(get: { effectiveMode }, set: { chosen = $0 })) {
            ForEach(modes) { Text($0.rawValue).tag($0) }
        }
        .pickerStyle(.segmented)
    }

    // MARK: Day: week strip + that day's events

    private func dayView(days: [String], day: String, events: [Occurrence]) -> some View {
        let d = model.dates
        return VStack(spacing: 12) {
            HStack(spacing: 4) {
                ForEach(days, id: \.self) { dd in
                    let on = dd == day
                    let has = events.contains { d.overlaps($0, day: dd) }
                    Button { selected = dd } label: {
                        VStack(spacing: 4) {
                            Text(String(d.dow(dd).prefix(1))).font(Theme.text(.caption2, .heavy))
                                .foregroundStyle(on ? .white : Theme.muted)
                            Text(d.dayNum(dd)).font(Theme.text(.headline, .heavy))
                                .foregroundStyle(on ? .white : dd == d.today ? Theme.accent : Theme.text)
                            Circle().fill(on ? .white : Theme.accent).frame(width: 5, height: 5).opacity(has ? 1 : 0)
                        }
                        .frame(maxWidth: .infinity).padding(.vertical, 8)
                        .background(on ? Theme.accent : .clear, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            ScrollView {
                VStack(spacing: 8) {
                    if let w = model.weather?.day(day) {
                        HStack(spacing: 6) {
                            WeatherGlyph(condition: w.condition, size: 18)
                            Text("\(w.high)° / \(w.low)°").font(Theme.text(.subheadline, .heavy))
                            Spacer()
                            if let dinner = meals.first(where: { $0.date == day && $0.slot == "dinner" }) {
                                Text("🍽️ \(dinner.title)").font(Theme.text(.subheadline)).foregroundStyle(Theme.mealText).lineLimit(1)
                            }
                        }
                        .padding(.horizontal, 4)
                    }
                    let list = AgendaItem.make(events.filter { d.overlaps($0, day: day) }, day: day)
                    if list.isEmpty { EmptyHint(text: "Nothing planned") }
                    ForEach(list) { item in AgendaRow(item: item) { open = $0 } }
                }
                .padding(.horizontal, 16).padding(.bottom, 24)
            }
            .refreshable { model.bump("events") }
        }
        .simultaneousGesture(DragGesture(minimumDistance: 30).onEnded { g in
            // Swipe left/right between days.
            guard abs(g.translation.width) > abs(g.translation.height) * 1.5 else { return }
            selected = d.addDays(day, g.translation.width < 0 ? 1 : -1)
        })
    }

    // MARK: Week grid (medium and wide)

    private func weekView(days: [String], events: [Occurrence]) -> some View {
        let d = model.dates
        return HStack(alignment: .top, spacing: 8) {
            ForEach(days, id: \.self) { day in
                let isToday = day == d.today
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(d.dow(day)).font(Theme.text(.caption2, .heavy)).foregroundStyle(isToday ? Theme.accent : Theme.muted)
                            Text(d.dayNum(day)).font(Theme.text(.title3, .heavy)).foregroundStyle(isToday ? Theme.accent : Theme.text)
                        }
                        Spacer(minLength: 0)
                        if let w = model.weather?.day(day), room == .wide {
                            WeatherGlyph(condition: w.condition, size: 14)
                            Text("\(w.high)°").font(Theme.text(.caption, .heavy))
                        }
                    }
                    .padding(.horizontal, 8).padding(.top, 8)
                    ScrollView {
                        VStack(spacing: 5) {
                            ForEach(AgendaItem.make(events.filter { d.overlaps($0, day: day) }, day: day)) { item in
                                AgendaRow(item: item, compact: true) { open = $0 }
                            }
                        }
                        .padding(.horizontal, 5)
                    }
                    if let dinner = meals.first(where: { $0.date == day && $0.slot == "dinner" }) {
                        Text("🍽️ \(dinner.title)").font(Theme.text(.caption2, .bold)).foregroundStyle(Theme.mealText).lineLimit(1)
                            .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.mealBg, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                            .padding(5)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay { if isToday { RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Theme.accent, lineWidth: 2) } }
                .contentShape(Rectangle())
                .onTapGesture(count: 2) { adding = day }
            }
        }
        .padding(.horizontal, 12).padding(.bottom, 12)
    }

    // MARK: Schedule

    private func scheduleView(days: [String], events: [Occurrence]) -> some View {
        let d = model.dates
        return List {
            ForEach(days, id: \.self) { day in
                let list = AgendaItem.make(events.filter { d.overlaps($0, day: day) }, day: day)
                if !list.isEmpty || day == d.today {
                    Section {
                        if list.isEmpty { Text("Nothing planned").foregroundStyle(Theme.muted) }
                        ForEach(list) { item in
                            AgendaRow(item: item) { open = $0 }
                                .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                                .listRowSeparator(.hidden)
                                .listRowBackground(Color.clear)
                        }
                    } header: {
                        HStack {
                            Text(d.relative(day)).font(Theme.text(.subheadline, .heavy))
                                .foregroundStyle(day == d.today ? Theme.accent : Theme.text)
                            Spacer()
                            if let w = model.weather?.day(day) {
                                WeatherGlyph(condition: w.condition, size: 14)
                                Text("\(w.high)°").font(Theme.text(.caption, .heavy))
                            }
                        }
                    }
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }
}
