import SwiftUI

/// The chore chart. Narrow: pick a person (or everyone) and get one list. Wider: a column per person,
/// as many as fit, scrolling sideways for the rest.
struct ChoresScreen: View {
    @Environment(AppModel.self) private var model
    @State private var date: String?
    @State private var focus: String? // person id on narrow screens, nil = everyone
    @State private var chores: [ChoreDay] = []
    @State private var points: [Balance] = []
    @State private var editing: ChoreEdit?
    @State private var celebrate = 0
    @State private var celebrating: Person?

    struct ChoreEdit: Identifiable {
        let chore: ChoreDay?
        let personId: String?
        var id: String { chore?.id ?? "new-\(personId ?? "")" }
    }

    var body: some View {
        let d = model.dates
        let day = date ?? d.today
        Page(title: d.relative(day)) { room in
            if model.people.isEmpty {
                EmptyHint(text: "Add your family in Settings › Family to start a chore chart.").padding(.top, 40)
            } else if room == .narrow {
                narrow(day: day)
            } else {
                columns(day: day, room: room)
            }
        } tools: {
            ToolbarItem(placement: .topBarLeading) {
                DateStepper(label: "Today", onToday: { date = nil }) { date = d.addDays(day, $0) }
            }
            ToolbarItem(placement: .primaryAction) {
                Button { editing = ChoreEdit(chore: nil, personId: focus) } label: { Image(systemName: "plus") }
                    .accessibilityLabel("New chore")
            }
        }
        .overlay { if let celebrating { CelebrationBurst(person: celebrating) } }
        .sensoryFeedback(.success, trigger: celebrate)
        .task(id: "\(day)|\(model.rev("chores", "points"))") {
            if let v = await model.call({ try await $0.chores(day) }) { chores = v }
            if let v = await model.call({ try await $0.points() }) { points = v }
        }
        .sheet(item: $editing) { e in ChoreEditor(chore: e.chore, personId: e.personId ?? model.people.first?.id) }
    }

    // MARK: Narrow

    private func narrow(day: String) -> some View {
        List {
            Section {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 14) {
                        personChip(nil)
                        ForEach(model.people) { personChip($0) }
                    }
                    .padding(.vertical, 6)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
            }
            ForEach(model.people.filter { focus == nil || $0.id == focus }) { p in
                let mine = mineSorted(p)
                Section {
                    if mine.isEmpty { Text("No chores").foregroundStyle(Theme.muted) }
                    ForEach(mine) { c in
                        row(c, person: p, day: day)
                            .swipeActions(edge: .trailing) {
                                Button("Delete", role: .destructive) { delete(c) }
                                Button("Edit") { editing = ChoreEdit(chore: c, personId: c.person_id) }.tint(Theme.accent)
                            }
                    }
                } header: {
                    header(p, mine: mine)
                }
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
    }

    private func personChip(_ p: Person?) -> some View {
        let on = focus == p?.id
        return Button { withAnimation { focus = p?.id } } label: {
            VStack(spacing: 4) {
                if let p {
                    let mine = chores.filter { $0.person_id == p.id }
                    ProgressRing(person: p, done: mine.filter(\.completed).count, total: mine.count, size: 52)
                    Text(p.name).font(Theme.text(.caption, on ? .heavy : .semibold))
                } else {
                    Image(systemName: "person.3.fill").font(.system(size: 20))
                        .frame(width: 52, height: 52).background(Circle().fill(Theme.surface2))
                    Text("Everyone").font(Theme.text(.caption, on ? .heavy : .semibold))
                }
            }
            .foregroundStyle(on ? Theme.accent : Theme.text)
            .opacity(on || focus == nil ? 1 : 0.6)
        }
        .buttonStyle(.plain)
    }

    // MARK: Columns

    private func columns(day: String, room: Room) -> some View {
        GeometryReader { geo in
            let shown = max(1, min(model.people.count, room == .wide ? 4 : 2))
            let width = (geo.size.width - 16 - CGFloat(shown) * 12) / CGFloat(shown)
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(model.people) { p in
                        column(p, day: day).frame(width: max(width, 260))
                    }
                }
                .scrollTargetLayout()
                .padding(.horizontal, 16).padding(.bottom, 16)
                .frame(minHeight: geo.size.height, alignment: .top)
            }
            .scrollTargetBehavior(.viewAligned)
        }
    }

    private func column(_ p: Person, day: String) -> some View {
        let mine = mineSorted(p)
        return VStack(alignment: .leading, spacing: 10) {
            header(p, mine: mine)
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if mine.isEmpty { EmptyHint(text: "No chores") }
                    ForEach(TimeOfDay.allCases, id: \.self) { tod in
                        let group = mine.filter { $0.time_of_day == tod.rawValue }
                        if !group.isEmpty {
                            Text("\(tod.emoji) \(tod.label)").font(Theme.text(.caption2, .heavy)).kerning(1).foregroundStyle(Theme.muted)
                            ForEach(group) { c in
                                row(c, person: p, day: day)
                                    .padding(.horizontal, 12).padding(.vertical, 6)
                                    .background(c.completed ? Color(hex: p.color).opacity(0.14) : Theme.surface,
                                                in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                                    .contextMenu {
                                        Button("Edit", systemImage: "pencil") { editing = ChoreEdit(chore: c, personId: c.person_id) }
                                        Button("Delete", systemImage: "trash", role: .destructive) { delete(c) }
                                    }
                            }
                        }
                    }
                }
            }
        }
        .padding(14)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Color(hex: p.color).opacity(0.12), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    // MARK: Pieces

    private func mineSorted(_ p: Person) -> [ChoreDay] {
        let order = TimeOfDay.allCases.map(\.rawValue)
        return chores.filter { $0.person_id == p.id }
            .sorted { (order.firstIndex(of: $0.time_of_day) ?? 9, $0.sort) < (order.firstIndex(of: $1.time_of_day) ?? 9, $1.sort) }
    }

    private func header(_ p: Person, mine: [ChoreDay]) -> some View {
        let done = mine.filter(\.completed).count
        return HStack(spacing: 10) {
            ProgressRing(person: p, done: done, total: mine.count, size: 40)
            VStack(alignment: .leading, spacing: 0) {
                Text(p.name).font(Theme.text(.headline, .heavy)).foregroundStyle(Theme.text)
                Text(!mine.isEmpty && done == mine.count ? "All done! 🎉" : "\(done) of \(mine.count) done")
                    .font(Theme.text(.caption)).foregroundStyle(Theme.muted)
            }
            .textCase(nil)
            Spacer()
            if p.isChild { StarBadge(value: points.first { $0.person_id == p.id }?.balance ?? 0, size: 13) }
        }
    }

    private func row(_ c: ChoreDay, person: Person, day: String) -> some View {
        let color = Color(hex: person.color)
        return Button { toggle(c, person: person, day: day) } label: {
            HStack(spacing: 12) {
                Text(c.emoji.isEmpty ? "✅" : c.emoji).font(.system(size: 26))
                VStack(alignment: .leading, spacing: 2) {
                    Text(c.title).font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.text)
                        .strikethrough(c.completed).opacity(c.completed ? 0.6 : 1)
                    HStack(spacing: 8) {
                        if c.points > 0 { Label("\(c.points)", systemImage: "star.fill").labelStyle(TintedLabel(tint: Theme.star)) }
                        if c.streak > 1 { Label("\(c.streak)", systemImage: "flame.fill").labelStyle(TintedLabel(tint: .orange)) }
                    }
                    .font(Theme.text(.caption, .heavy))
                }
                Spacer()
                ZStack {
                    Circle().strokeBorder(color, lineWidth: 2.5)
                    if c.completed {
                        Circle().fill(color)
                        Image(systemName: "checkmark").font(.system(size: 15, weight: .heavy)).foregroundStyle(.white)
                    }
                }
                .frame(width: 34, height: 34)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(c.title), \(c.completed ? "done" : "not done")")
    }

    private func toggle(_ c: ChoreDay, person: Person, day: String) {
        let done = !c.completed
        if let i = chores.firstIndex(where: { $0.id == c.id }) { chores[i].completed = done }
        let mine = chores.filter { $0.person_id == person.id }
        if done && mine.allSatisfy(\.completed) {
            celebrate += 1
            withAnimation(.spring) { celebrating = person }
            Task {
                try? await Task.sleep(for: .seconds(2))
                withAnimation { celebrating = nil }
            }
        }
        Task {
            _ = await model.call { try await $0.setChore(c.id, date: day, done: done) }
            model.bump("chores")
        }
    }

    private func delete(_ c: ChoreDay) {
        chores.removeAll { $0.id == c.id }
        Task {
            _ = await model.call { try await $0.deleteChore(c.id) }
            model.bump("chores")
        }
    }
}

struct TintedLabel: LabelStyle {
    var tint: Color
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 3) {
            configuration.icon.foregroundStyle(tint)
            configuration.title.foregroundStyle(Theme.muted)
        }
    }
}

/// A burst of stars when someone finishes everything.
struct CelebrationBurst: View {
    let person: Person
    @State private var go = false

    var body: some View {
        ZStack {
            ForEach(0..<18, id: \.self) { i in
                let angle = Double(i) / 18 * 2 * .pi
                Image(systemName: i % 3 == 0 ? "sparkle" : "star.fill")
                    .font(.system(size: CGFloat(16 + (i * 7) % 16)))
                    .foregroundStyle(i % 2 == 0 ? Theme.star : Color(hex: person.color))
                    .offset(x: go ? cos(angle) * CGFloat(120 + (i * 37) % 90) : 0,
                            y: go ? sin(angle) * CGFloat(120 + (i * 53) % 90) : 0)
                    .opacity(go ? 0 : 1)
            }
            VStack(spacing: 6) {
                Text("🎉").font(.system(size: 56))
                Text("All done, \(person.name)!").font(Theme.text(.title2, .heavy))
            }
            .padding(24)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .scaleEffect(go ? 1 : 0.6)
        }
        .allowsHitTesting(false)
        .onAppear { withAnimation(.easeOut(duration: 1.4)) { go = true } }
    }
}

/// Add or edit a chore: what, who, stars, when.
struct ChoreEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let chore: ChoreDay?
    let personId: String?

    @State private var title = ""
    @State private var emoji = ""
    @State private var person: String = ""
    @State private var points = 1
    @State private var tod = "anytime"
    @State private var type = "daily"
    @State private var days: Set<String> = ["MO", "TU", "WE", "TH", "FR"]
    @State private var once = Date()
    @State private var error: String?
    @State private var loaded = false

    private struct Weekday: Hashable { let code: String; let letter: String }
    private let weekdays = [("MO", "M"), ("TU", "T"), ("WE", "W"), ("TH", "T"), ("FR", "F"), ("SA", "S"), ("SU", "S")]
        .map { Weekday(code: $0.0, letter: $0.1) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        TextField("🧹", text: $emoji).frame(width: 44).font(.system(size: 28))
                            .onChange(of: emoji) { if emoji.count > 1 { emoji = String(emoji.suffix(1)) } }
                        TextField("Chore", text: $title).font(Theme.text(.headline))
                    }
                }
                Section {
                    Picker("Who", selection: $person) {
                        ForEach(model.people) { Text($0.name).tag($0.id) }
                    }
                    Stepper(value: $points, in: 0...50) {
                        Label("\(points) star\(points == 1 ? "" : "s")", systemImage: "star.fill").labelStyle(TintedLabel(tint: Theme.star))
                    }
                    Picker("Time of day", selection: $tod) {
                        ForEach(TimeOfDay.allCases, id: \.rawValue) { Text("\($0.emoji) \($0.rawValue.capitalized)").tag($0.rawValue) }
                    }
                }
                Section("Repeat") {
                    Picker("Repeat", selection: $type) {
                        Text("Every day").tag("daily")
                        Text("Some days").tag("weekly")
                        Text("Once").tag("once")
                    }
                    .pickerStyle(.segmented)
                    if type == "weekly" {
                        HStack {
                            ForEach(weekdays, id: \.code) { wd in
                                let code = wd.code
                                let on = days.contains(code)
                                Button {
                                    if on { days.remove(code) } else { days.insert(code) }
                                } label: {
                                    Text(wd.letter).font(Theme.text(.subheadline, .heavy))
                                        .frame(width: 36, height: 36)
                                        .background(Circle().fill(on ? Theme.accent : Theme.surface2))
                                        .foregroundStyle(on ? .white : Theme.text)
                                }
                                .buttonStyle(.plain)
                                .frame(maxWidth: .infinity)
                            }
                        }
                    }
                    if type == "once" { DatePicker("On", selection: $once, displayedComponents: .date) }
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle(chore == nil ? "New chore" : "Edit chore")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || person.isEmpty || (type == "weekly" && days.isEmpty))
                }
            }
            .onAppear(perform: load)
        }
    }

    private func load() {
        guard !loaded else { return }
        loaded = true
        person = personId ?? model.people.first?.id ?? ""
        guard let c = chore else { return }
        title = c.title
        emoji = c.emoji
        person = c.person_id
        points = c.points
        tod = c.time_of_day
        type = c.schedule.type
        if let d = c.schedule.days { days = Set(d) }
        if let d = c.schedule.date { once = model.dates.date(d) }
    }

    private func save() async {
        let schedule = ChoreSchedule(type: type, days: weekdays.map(\.code).filter(days.contains), date: model.dates.iso(once))
        let body: [String: Any] = [
            "title": title.trimmingCharacters(in: .whitespaces), "emoji": emoji, "person_id": person,
            "points": points, "time_of_day": tod, "schedule": schedule.json,
        ]
        do {
            try await model.api?.saveChore(id: chore?.id, body)
            model.bump("chores")
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
