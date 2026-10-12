import SwiftUI

/// The chore chart: a column per person, chores by time of day. Select a chore to tick it off (or undo).
struct ChoresView: View {
    @Environment(AppModel.self) private var model
    @State private var date: String?
    @State private var kidsOnly = false
    @State private var chores: [ChoreDay] = []
    @State private var points: [Balance] = []
    @State private var celebrating: Person?
    @FocusState private var focused: String?

    var body: some View {
        let d = model.dates
        let day = date ?? d.today
        let people = kidsOnly ? model.kids : model.people
        Screen {
            HStack(spacing: 18) {
                Button("Today") { date = nil }.buttonStyle(.pill)
                Button { date = d.addDays(day, -1) } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(.pill).accessibilityLabel("Previous day")
                Button { date = d.addDays(day, 1) } label: { Image(systemName: "chevron.right") }
                    .buttonStyle(.pill).accessibilityLabel("Next day")
                Text(d.relative(day)).font(Theme.font(40, .heavy)).foregroundStyle(Theme.text).padding(.leading, 10)
                if day == d.today || day == d.addDays(d.today, 1) {
                    Text(d.dayMonth(day)).font(Theme.font(28, .bold)).foregroundStyle(Theme.muted)
                }
                Spacer()
                Picker("Who", selection: $kidsOnly) {
                    Text("Everyone").tag(false)
                    Text("Kids").tag(true)
                }
                .pickerStyle(.segmented)
                .frame(width: 360)
            }
            .focusSection()

            if people.isEmpty {
                FamilyPrompt(text: model.people.isEmpty
                             ? "Add your family in Moonlight Settings › Family to start a chore chart."
                             : "Add a child in Moonlight Settings › Family to give them chores.")
            } else {
                HStack(alignment: .top, spacing: 20) {
                    ForEach(people) { p in
                        column(p, day: day)
                    }
                }
                .padding(.bottom, 40)
                // Down from the buttons above lands in the chart even when the column below them has no chores.
                .focusSection()
            }
        }
        // Start on the first chore still to do (in the first column that has one), not the buttons at the top.
        .defaultFocus($focused, people.lazy.compactMap { p in ordered(p).first { !$0.completed }?.id }.first)
        .overlay { if let celebrating { Celebration(person: celebrating) } }
        .task(id: "\(day)|\(model.rev("chores", "points"))") {
            if let v = await model.call({ try await $0.chores(day) }) { chores = v }
            if let v = await model.call({ try await $0.points() }) { points = v }
        }
    }

    private func column(_ p: Person, day: String) -> some View {
        let color = Color(hex: p.color)
        let mine = ordered(p)
        let done = mine.filter(\.completed).count
        return VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 16) {
                ProgressRing(person: p, done: done, total: mine.count, size: 84)
                VStack(alignment: .leading, spacing: 2) {
                    Text(p.name).font(Theme.font(32, .heavy)).foregroundStyle(Theme.text)
                    Text("\(done) of \(mine.count) done").font(Theme.font(22, .bold)).foregroundStyle(Theme.muted)
                }
                Spacer()
                if p.isChild { StarBadge(value: points.first { $0.person_id == p.id }?.balance ?? 0, size: 24) }
            }
            if !mine.isEmpty && done == mine.count {
                Text("All done! 🎉").font(Theme.font(28, .heavy)).foregroundStyle(color)
                    .frame(maxWidth: .infinity).padding(.vertical, 12)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if mine.isEmpty { EmptyNote(text: "No chores") }
                    ForEach(TimeOfDay.allCases, id: \.self) { tod in
                        let group = mine.filter { $0.time_of_day == tod.rawValue }
                        if !group.isEmpty {
                            Text("\(tod.emoji) \(tod.label)").font(Theme.font(19, .heavy)).kerning(1.2)
                                .foregroundStyle(Theme.muted).padding(.top, 8)
                            ForEach(group) { c in row(c, person: p, day: day) }
                        }
                    }
                }
                .padding(.horizontal, 6).padding(.vertical, 36)  // room for a focused row's shadow at the ends
            }
            .clipTopAndBottom()
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .focusSection()
    }

    /// A person's chores in the order the column shows them: by time of day, then their own order.
    private func ordered(_ p: Person) -> [ChoreDay] {
        let mine = chores.filter { $0.person_id == p.id }.sorted { $0.sort < $1.sort }
        return TimeOfDay.allCases.flatMap { tod in mine.filter { $0.time_of_day == tod.rawValue } }
    }

    private func row(_ c: ChoreDay, person: Person, day: String) -> some View {
        let color = Color(hex: person.color)
        return Button { toggle(c, person: person, day: day) } label: {
            HStack(spacing: 16) {
                Text(c.emoji).font(.system(size: 40))
                VStack(alignment: .leading, spacing: 4) {
                    Text(c.title).font(Theme.font(26, .heavy)).foregroundStyle(Theme.text)
                        .strikethrough(c.completed).opacity(c.completed ? 0.6 : 1).lineLimit(1)
                    HStack(spacing: 12) {
                        if c.points > 0 {
                            Label("\(c.points)", systemImage: "star.fill").labelStyle(StarLabelStyle())
                        }
                        if c.streak > 1 {
                            Label("\(c.streak)", systemImage: "flame.fill").labelStyle(StarLabelStyle(tint: .orange))
                        }
                    }
                    .font(Theme.font(19, .heavy))
                }
                Spacer()
                ZStack {
                    Circle().strokeBorder(color, lineWidth: 4)
                    if c.completed {
                        Circle().fill(color)
                        Image(systemName: "checkmark").font(.system(size: 26, weight: .heavy)).foregroundStyle(.white)
                    }
                }
                .frame(width: 58, height: 58)
            }
            .padding(.horizontal, 18).padding(.vertical, 14)
            .background(c.completed ? color.opacity(0.14) : Theme.surface)
            .background(Theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .buttonStyle(.moonCard(radius: 18, ring: color))
        .focused($focused, equals: c.id)
        .accessibilityLabel("\(c.title), \(c.completed ? "done" : "not done")")
    }

    private func toggle(_ c: ChoreDay, person: Person, day: String) {
        let done = !c.completed
        if let i = chores.firstIndex(where: { $0.id == c.id }) { chores[i].completed = done } // optimistic
        let mine = chores.filter { $0.person_id == person.id }
        if done && !mine.isEmpty && mine.allSatisfy(\.completed) {
            withAnimation(.spring) { celebrating = person }
            Task {
                try? await Task.sleep(for: .seconds(2.5))
                withAnimation { celebrating = nil }
            }
        }
        Task {
            _ = await model.call { try await $0.setChore(c.id, date: day, done: done) }
            model.bump("chores")
        }
    }
}

struct StarLabelStyle: LabelStyle {
    var tint: Color = Theme.star
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) {
            configuration.icon.foregroundStyle(tint)
            configuration.title.foregroundStyle(Theme.muted)
        }
    }
}

/// A burst of stars when someone finishes all their chores.
struct Celebration: View {
    let person: Person
    @State private var go = false

    var body: some View {
        ZStack {
            ForEach(0..<24, id: \.self) { i in
                let angle = Double(i) / 24 * 2 * .pi
                Image(systemName: i % 3 == 0 ? "sparkle" : "star.fill")
                    .font(.system(size: CGFloat(30 + (i * 7) % 30)))
                    .foregroundStyle(i % 2 == 0 ? Theme.star : Color(hex: person.color))
                    .offset(x: go ? cos(angle) * CGFloat(260 + (i * 37) % 200) : 0,
                            y: go ? sin(angle) * CGFloat(200 + (i * 53) % 160) : 0)
                    .opacity(go ? 0 : 1)
            }
            VStack(spacing: 12) {
                Text("🎉").font(.system(size: 120))
                Text("All done, \(person.name)!").font(Theme.font(64, .heavy)).foregroundStyle(Theme.text)
            }
            .padding(50)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 40, style: .continuous))
            .scaleEffect(go ? 1 : 0.6)
        }
        .allowsHitTesting(false)
        .onAppear { withAnimation(.easeOut(duration: 1.6)) { go = true } }
    }
}
