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
                    LabeledContent("Version", value: version ?? "—")
                    LabeledContent("This device", value: status?.display?.name ?? "—")
                    LabeledContent("Live updates", value: model.connected ? "Connected" : "Reconnecting…")
                }
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
