import SwiftUI

/// One event as the screens draw it: tinted card, person-coloured stripe, time above title.
struct EventRow: View {
    @Environment(AppModel.self) private var model
    let event: Occurrence
    var compact = false

    var body: some View {
        let colors = EventColors(event, people: model.people)
        let people = event.person_ids.compactMap(model.person)
        if event.all_day {
            HStack {
                Text(event.displayTitle(model.people)).font(Theme.text(compact ? .caption : .subheadline, .heavy)).lineLimit(1)
                Spacer(minLength: 4)
                if people.count > 1 && !compact { AvatarStack(people: people, size: 20) }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 10).padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(colors.main, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        } else {
            HStack(spacing: 0) {
                VStack(spacing: 0) {
                    ForEach(Array(colors.stripe.enumerated()), id: \.offset) { item in item.element }
                }
                .frame(width: 5)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.dates.range(event))
                        .font(Theme.text(.caption, .bold))
                        .foregroundStyle(colors.main.mix(with: .black, by: 0.3))
                    Text(event.displayTitle(model.people))
                        .font(Theme.text(compact ? .footnote : .subheadline, .heavy))
                        .foregroundStyle(Theme.text)
                        .lineLimit(2)
                    if !compact, let loc = event.location, !loc.isEmpty {
                        Text(loc).font(Theme.text(.caption, .semibold)).foregroundStyle(Theme.muted).lineLimit(1)
                    }
                    if people.count > 1 && !compact { AvatarStack(people: people, size: 20).padding(.top, 2) }
                }
                .padding(.horizontal, 10).padding(.vertical, 8)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(colors.main.opacity(colors.busy ? 0.08 : 0.16))
            .background(Theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .contentShape(Rectangle())
        }
    }
}

/// A day's work busy time as one card: "Chris busy", first start to last finish, the free gaps and anything tentative.
struct BusyRow: View {
    @Environment(AppModel.self) private var model
    let busy: BusyDay
    var compact = false

    var body: some View {
        let color = Color(hex: busy.color ?? model.person(busy.personIds.first)?.color ?? Theme.fallbackEvent)
        HStack(spacing: 0) {
            Rectangle().fill(color.opacity(busy.allTentative ? 0.45 : 1)).frame(width: 5)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(model.dates.clock(minutes: busy.start)) – \(model.dates.clock(minutes: busy.end))")
                    .font(Theme.text(.caption, .bold))
                    .foregroundStyle(color.mix(with: .black, by: 0.3))
                Text(busy.who(model.people))
                    .font(Theme.text(compact ? .footnote : .subheadline, .heavy))
                    .foregroundStyle(Theme.text)
                    .lineLimit(1)
                ForEach(busy.details(model.dates), id: \.self) { line in
                    Text(line).font(Theme.text(.caption, .semibold)).foregroundStyle(Theme.muted).lineLimit(compact ? 2 : 3)
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.08))
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// An event or a folded busy line, as a list row. Events open their details.
struct AgendaRow: View {
    let item: AgendaItem
    var compact = false
    let onOpen: (Occurrence) -> Void

    var body: some View {
        switch item {
        case .event(let ev):
            Button { onOpen(ev) } label: { EventRow(event: ev, compact: compact) }.buttonStyle(.plain)
        case .busy(let b):
            BusyRow(busy: b, compact: compact)
        }
    }
}

/// Details sheet with Edit and Delete for events Moonlight can change.
struct EventDetailSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let event: Occurrence
    @State private var editing = false
    @State private var confirmDelete = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(event.displayTitle(model.people)).font(Theme.text(.title2, .heavy))
                        Text("\(model.dates.relative(event.startDay)) · \(model.dates.range(event))")
                            .font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
                    }
                    .listRowBackground(EventColors(event, people: model.people).main.opacity(0.14))
                }
                if let loc = event.location, !loc.isEmpty {
                    Label(loc, systemImage: "mappin.and.ellipse")
                }
                if event.recurring == true || event.custom_repeat == true {
                    Label(event.custom_repeat == true ? "Repeats (set up in the calendar app)" : repeatText(event.`repeat`), systemImage: "repeat")
                }
                let people = event.person_ids.compactMap(model.person)
                if !people.isEmpty {
                    Section("Who") {
                        ForEach(people) { p in
                            HStack { Avatar(person: p, size: 30); Text(p.name).font(Theme.text(.body)) }
                        }
                    }
                }
                if let notes = event.notes, !notes.isEmpty {
                    Section("Notes") { Text(notes) }
                }
                if event.editable {
                    Section {
                        Button("Edit event") { editing = true }
                        Button("Delete event", role: .destructive) { confirmDelete = true }
                    } footer: {
                        if event.recurring == true { Text("Changes apply to every repeat.") }
                    }
                } else if event.read_only == true || event.busy != nil {
                    Section { Text("This calendar is read-only in Moonlight.").foregroundStyle(Theme.muted) }
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle("Event")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $editing) { EventEditor(event: event) { dismiss() } }
            .confirmationDialog("Delete \(event.title)?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) {
                    Task {
                        do {
                            try await model.api?.deleteEvent(event.id)
                            model.bump("events")
                            dismiss()
                        } catch { self.error = error.localizedDescription }
                    }
                }
            } message: {
                if event.recurring == true { Text("This deletes every repeat.") }
            }
        }
    }
}

extension EventEditor {
    /// The repeat to save. Keeps what the app can't edit (interval, weekdays, end date) while the frequency is unchanged.
    fileprivate func repeatBody() -> [String: Any] {
        var out: [String: Any] = ["freq": freq, "interval": 1, "skip_holidays": skipHolidays]
        if let r = event?.`repeat`, r.freq == freq {
            out["interval"] = r.interval
            if let byday = r.byday { out["byday"] = byday }
            if let until = r.until { out["until"] = until }
        }
        return out
    }
}

func repeatText(_ r: Repeat?) -> String {
    guard let r else { return "Repeats" }
    let unit = ["daily": "day", "weekly": "week", "monthly": "month"][r.freq] ?? r.freq
    return r.interval == 1 ? "Every \(unit)" : "Every \(r.interval) \(unit)s"
}

/// Add or edit an event: title, who, when, where, repeat.
struct EventEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var event: Occurrence? = nil
    var day: String? = nil
    var onSaved: () -> Void = {}

    @State private var title = ""
    @State private var people: Set<String> = []
    @State private var allDay = false
    @State private var start = Date()
    @State private var end = Date().addingTimeInterval(3600)
    @State private var location = ""
    @State private var notes = ""
    @State private var freq = "none"
    @State private var skipHolidays = false
    @State private var saving = false
    @State private var error: String?
    @State private var loaded = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Title", text: $title).font(Theme.text(.headline))
                }
                Section("Who") {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 14) {
                            ForEach(model.people) { p in
                                Button {
                                    if people.contains(p.id) { people.remove(p.id) } else { people.insert(p.id) }
                                } label: {
                                    VStack(spacing: 4) {
                                        Avatar(person: p, size: 44, dim: !people.contains(p.id))
                                        Text(p.name).font(Theme.text(.caption)).foregroundStyle(Theme.text)
                                    }
                                }
                                .buttonStyle(.plain)
                                .accessibilityAddTraits(people.contains(p.id) ? .isSelected : [])
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
                Section {
                    Toggle("All day", isOn: $allDay)
                    DatePicker("Starts", selection: $start, displayedComponents: allDay ? DatePickerComponents.date : [.date, .hourAndMinute])
                    DatePicker("Ends", selection: $end, in: start..., displayedComponents: allDay ? DatePickerComponents.date : [.date, .hourAndMinute])
                    Picker("Repeat", selection: $freq) {
                        Text("Never").tag("none")
                        Text("Every day").tag("daily")
                        Text("Every week").tag("weekly")
                        Text("Every month").tag("monthly")
                    }
                    .disabled(event?.custom_repeat == true)
                    if freq != "none" && event?.custom_repeat != true {
                        Toggle("Skip public holidays", isOn: $skipHolidays)
                    }
                }
                Section {
                    TextField("Location", text: $location)
                    TextField("Notes", text: $notes, axis: .vertical).lineLimit(3...8)
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle(event == nil ? "New event" : "Edit event")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || saving)
                }
            }
            .onAppear(perform: load)
            .onChange(of: start) { old, new in
                // Keep the length when the start moves, like Calendar does.
                end = new.addingTimeInterval(max(end.timeIntervalSince(old), allDay ? 0 : 900))
            }
        }
    }

    private func load() {
        guard !loaded else { return }
        loaded = true
        let d = model.dates
        if let e = event {
            title = e.title
            people = Set(e.person_ids)
            allDay = e.all_day
            start = d.date(e.start)
            // All-day ends are exclusive (next midnight): show the last day.
            end = e.all_day ? d.date(d.addDays(String(e.end.prefix(10)), -1)) : d.date(e.end)
            location = e.location ?? ""
            notes = e.notes ?? ""
            freq = e.`repeat`?.freq ?? "none"
            skipHolidays = e.`repeat`?.skip_holidays == true
        } else {
            let base = day ?? d.today
            let now = d.calendar.dateComponents([.hour], from: Date()).hour ?? 9
            let hour = base == d.today ? min(now + 1, 22) : 9
            start = d.date("\(base)T\(String(format: "%02d", hour)):00")
            end = start.addingTimeInterval(3600)
        }
    }

    private func save() async {
        guard let api = model.api else { return }
        let d = model.dates
        saving = true
        defer { saving = false }
        var body: [String: Any] = [
            "title": title.trimmingCharacters(in: .whitespaces),
            "person_ids": model.people.map(\.id).filter(people.contains),
            "all_day": allDay,
            "location": location,
            "notes": notes,
        ]
        if allDay {
            body["start"] = d.iso(start) + "T00:00"
            body["end"] = d.addDays(d.iso(max(end, start)), 1) + "T00:00"
        } else {
            body["start"] = d.isoDT(start)
            body["end"] = d.isoDT(max(end, start))
        }
        if event?.custom_repeat != true {
            body["repeat"] = freq == "none" ? NSNull() as Any : repeatBody() as Any
        }
        do {
            try await api.saveEvent(id: event?.id, body)
            model.bump("events")
            dismiss()
            onSaved()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
