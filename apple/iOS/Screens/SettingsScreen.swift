import SwiftUI

struct SettingsScreen: View {
    @Environment(AppModel.self) private var model
    @State private var status: AuthStatus?
    @State private var version: String?
    @State private var confirmForget = false

    var body: some View {
        NavigationStack {
            List {
                Section("Connected to") {
                    LabeledContent("Moonlight", value: model.api?.baseURL.host ?? "—")
                    if model.away { LabeledContent("Using", value: "Public address (away from home)") }
                    LabeledContent("Version", value: version ?? "—")
                    LabeledContent("This device", value: status?.display?.name ?? "—")
                    LabeledContent("Live updates", value: model.connected ? "Connected" : "Reconnecting…")
                }
                ReminderSettings()
                Section("Family") {
                    LabeledContent("Name", value: model.settings?.family_name ?? "—")
                    ForEach(model.people) { p in
                        HStack { Avatar(person: p, size: 30); Text(p.name); Spacer(); Text(p.role.capitalized).foregroundStyle(Theme.muted) }
                    }
                }
                Section {
                    Button("Forget this Moonlight", role: .destructive) { confirmForget = true }
                } footer: {
                    Text("Family members, calendars, music and photos are set up in Moonlight's Settings on a wall screen or in the Home Assistant sidebar.")
                }
            }
            .navigationTitle("Settings")
            .task {
                status = await model.call { try await $0.authStatus() }
                version = await model.call { try await $0.health() }?.version
            }
            .confirmationDialog("Forget this Moonlight?", isPresented: $confirmForget, titleVisibility: .visible) {
                Button("Forget", role: .destructive) { model.forget() }
            } message: {
                Text("You'll need a new pairing code to connect again. To remove this device completely, delete it in Settings › Screens.")
            }
        }
    }
}

/// Settings › Reminders: notifications before events (for chosen people) and an evening chores nudge.
struct ReminderSettings: View {
    @Environment(AppModel.self) private var model
    @AppStorage(Reminders.Key.events) private var events = false
    @AppStorage(Reminders.Key.lead) private var lead = Reminders.defaultLead
    @AppStorage(Reminders.Key.people) private var peopleIds = ""
    @AppStorage(Reminders.Key.chores) private var chores = false
    @AppStorage(Reminders.Key.choresAt) private var choresAt = Reminders.defaultChoresAt
    @State private var denied = false

    var body: some View {
        Section {
            Toggle("Before events", isOn: $events)
            if events {
                Picker("Remind me", selection: $lead) {
                    ForEach(Reminders.leadChoices, id: \.self) { m in
                        Text(m < 60 ? "\(m) minutes before" : "\(m / 60) hour\(m == 60 ? "" : "s") before").tag(m)
                    }
                }
                NavigationLink {
                    PeoplePicker(ids: $peopleIds)
                } label: {
                    LabeledContent("For", value: whose)
                }
            }
            Toggle("Chores left in the evening", isOn: $chores)
            if chores {
                DatePicker("At", selection: choresTime, displayedComponents: .hourAndMinute)
            }
        } header: {
            Text("Reminders")
        } footer: {
            Text(denied ? "Notifications are off for Moonlight. Turn them on in the Settings app › Notifications › Moonlight."
                 : "Reminders are worked out on this device and follow changes made on any screen.")
        }
        .onChange(of: events) { _, on in changed(on) }
        .onChange(of: chores) { _, on in changed(on) }
        .onChange(of: lead) { model.bump("reminders") }
        .onChange(of: peopleIds) { model.bump("reminders") }
        .onChange(of: choresAt) { model.bump("reminders") }
    }

    private var whose: String {
        let ids = Set(peopleIds.split(separator: ",").map(String.init))
        let names = model.people.filter { ids.contains($0.id) }.map(\.name)
        return names.isEmpty ? "Everyone" : names.joined(separator: ", ")
    }

    private var choresTime: Binding<Date> {
        Binding {
            Calendar.current.date(bySettingHour: choresAt / 60, minute: choresAt % 60, second: 0, of: Date()) ?? Date()
        } set: { date in
            let c = Calendar.current.dateComponents([.hour, .minute], from: date)
            choresAt = (c.hour ?? 18) * 60 + (c.minute ?? 0)
        }
    }

    private func changed(_ on: Bool) {
        Task {
            if on { denied = !(await Reminders.requestPermission()) }
            if !Reminders.anyOn { denied = false }
            Reminders.scheduleRefresh()
            model.bump("reminders")
        }
    }
}

private struct PeoplePicker: View {
    @Environment(AppModel.self) private var model
    @Binding var ids: String

    var body: some View {
        let chosen = Set(ids.split(separator: ",").map(String.init))
        List {
            Section {
                ForEach(model.people) { p in
                    Button {
                        var next = chosen
                        if next.contains(p.id) { next.remove(p.id) } else { next.insert(p.id) }
                        ids = model.people.map(\.id).filter(next.contains).joined(separator: ",")
                    } label: {
                        HStack {
                            Avatar(person: p, size: 30)
                            Text(p.name).foregroundStyle(Theme.text)
                            Spacer()
                            if chosen.contains(p.id) { Image(systemName: "checkmark").foregroundStyle(Theme.accent) }
                        }
                    }
                }
            } footer: {
                Text("Pick nobody for reminders about everyone's events.")
            }
        }
        .navigationTitle("Reminders for")
    }
}
