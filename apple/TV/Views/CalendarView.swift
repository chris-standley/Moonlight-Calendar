import SwiftUI

/// Week grid and a two-week schedule, with per-person filters, like the hallway screen.
struct CalendarView: View {
    enum Mode: String, CaseIterable, Identifiable {
        case week = "Week", schedule = "Schedule"
        var id: String { rawValue }
    }

    @Environment(AppModel.self) private var model
    @State private var mode: Mode = .week
    @State private var anchor: String?
    @State private var hidden: Set<String> = []
    @State private var events: [Occurrence] = []
    @State private var meals: [Meal] = []
    @State private var open: Occurrence?

    var body: some View {
        let d = model.dates
        let today = d.today
        let start = mode == .week
            ? d.weekStart(anchor ?? today, start: model.settings?.week_start ?? "monday")
            : (anchor ?? today)
        let count = mode == .week ? 7 : 14
        let days = d.days(from: start, count: count)
        let end = d.addDays(start, count)
        let visible = events.filter { ev in ev.person_ids.isEmpty || ev.person_ids.contains { !hidden.contains($0) } }

        Screen {
            toolbar(days: days)
            switch mode {
            case .week: week(days: days, events: visible)
            case .schedule: schedule(days: days, events: visible)
            }
        }
        .task(id: "\(start)|\(end)|\(model.rev("events", "meals"))") {
            if let v = await model.call({ try await $0.events(start, end) }) { events = v }
            if let v = await model.call({ try await $0.meals(start, end) }) { meals = v }
        }
        .sheet(item: $open) { EventDetail(event: $0) }
    }

    private func toolbar(days: [String]) -> some View {
        let d = model.dates
        let step = mode == .week ? 7 : 14
        return HStack(spacing: 18) {
            Button("Today") { anchor = nil }.buttonStyle(.pill)
            Button { anchor = d.addDays(anchor ?? d.today, -step) } label: { Image(systemName: "chevron.left") }
                .buttonStyle(.pill).accessibilityLabel("Previous")
            Button { anchor = d.addDays(anchor ?? d.today, step) } label: { Image(systemName: "chevron.right") }
                .buttonStyle(.pill).accessibilityLabel("Next")
            Text("\(d.dayMonth(days.first!)) – \(d.dayMonth(days.last!))")
                .font(Theme.font(40, .heavy)).foregroundStyle(Theme.text)
                .padding(.leading, 10)
            Spacer()
            ForEach(model.people) { p in
                Button {
                    if hidden.contains(p.id) { hidden.remove(p.id) } else { hidden.insert(p.id) }
                } label: {
                    Avatar(person: p, size: 62, dim: hidden.contains(p.id))
                        .padding(4)
                        .overlay(Circle().stroke(Color(hex: p.color), lineWidth: hidden.contains(p.id) ? 0 : 3))
                }
                .buttonStyle(.moonCard(radius: 40, ring: Color(hex: p.color)))
                .accessibilityLabel("\(p.name), \(hidden.contains(p.id) ? "hidden" : "shown")")
            }
            Picker("View", selection: $mode) {
                ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .frame(width: 420)
            .padding(.leading, 12)
        }
        .focusSection()
    }

    private func sorted(_ list: [Occurrence]) -> [Occurrence] {
        list.sorted { ($0.all_day ? 0 : 1, $0.start) < ($1.all_day ? 0 : 1, $1.start) }
    }

    private func week(days: [String], events: [Occurrence]) -> some View {
        let d = model.dates
        let today = d.today
        return HStack(alignment: .top, spacing: 14) {
            ForEach(days, id: \.self) { day in
                let isToday = day == today
                VStack(alignment: .leading, spacing: 0) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(d.dow(day)).font(Theme.font(20, .heavy)).kerning(1.2)
                                .foregroundStyle(isToday ? Theme.accent : Theme.muted)
                            Text(d.dayNum(day))
                                .font(Theme.font(isToday ? 30 : 40, .heavy))
                                .foregroundStyle(isToday ? Color.white : Theme.text)
                                .frame(width: isToday ? 56 : nil, height: isToday ? 56 : nil)
                                .background { if isToday { Circle().fill(Theme.accent) } }
                        }
                        Spacer()
                        if let w = model.weather?.day(day) {
                            HStack(spacing: 4) {
                                WeatherGlyph(condition: w.condition, size: 22)
                                Text("\(w.high)°").font(Theme.font(20, .heavy))
                                Text("\(w.low)°").font(Theme.font(18, .bold)).foregroundStyle(Theme.muted)
                            }
                        }
                    }
                    .opacity(day < today ? 0.55 : 1)
                    .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 10)

                    ScrollView {
                        VStack(spacing: 10) {
                            ForEach(sorted(events.filter { d.overlaps($0, day: day) }), id: \.key) { ev in
                                EventCard(event: ev, compact: true) { open = $0 }
                            }
                        }
                        .padding(.horizontal, 10).padding(.vertical, 6)
                    }
                    .scrollClipDisabled()
                    .frame(maxHeight: .infinity)

                    if let dinner = meals.first(where: { $0.date == day && $0.slot == "dinner" }) {
                        Text("🍽️ \(dinner.title)")
                            .font(Theme.font(19, .bold)).foregroundStyle(Theme.mealText).lineLimit(1)
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.mealBg, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .padding(10)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                .overlay {
                    if isToday {
                        RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).strokeBorder(Theme.accent, lineWidth: 3)
                    }
                }
                .shadow(color: .black.opacity(0.05), radius: 10, y: 4)
                .focusSection()
            }
        }
        .padding(.bottom, 40)
    }

    private func schedule(days: [String], events: [Occurrence]) -> some View {
        let d = model.dates
        return ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                ForEach(days, id: \.self) { day in
                    let list = sorted(events.filter { d.overlaps($0, day: day) })
                    HStack(alignment: .top, spacing: 30) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(d.dow(day)).font(Theme.font(22, .heavy)).foregroundStyle(day == d.today ? Theme.accent : Theme.muted)
                            Text(d.dayNum(day)).font(Theme.font(48, .heavy)).foregroundStyle(Theme.text)
                            if let w = model.weather?.day(day) {
                                HStack(spacing: 4) {
                                    WeatherGlyph(condition: w.condition, size: 22)
                                    Text("\(w.high)°").font(Theme.font(20, .heavy)).foregroundStyle(Theme.text)
                                }
                            }
                        }
                        .frame(width: 140, alignment: .leading)
                        if list.isEmpty {
                            Text("Nothing planned").font(Theme.font(24, .bold)).foregroundStyle(Theme.muted).padding(.top, 20)
                        } else {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 480), spacing: 16)], alignment: .leading, spacing: 14) {
                                ForEach(list, id: \.key) { ev in EventCard(event: ev) { open = $0 } }
                            }
                        }
                    }
                    .padding(22)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                }
            }
            .padding(.vertical, 20)
        }
        .scrollClipDisabled()
    }
}
