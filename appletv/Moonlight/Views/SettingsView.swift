import SwiftUI

/// What this Apple TV is connected to. Everything else is set up on a wall screen or phone (it needs typing).
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var status: AuthStatus?
    @State private var version: String?
    @State private var confirmForget = false

    var body: some View {
        Screen {
            Text("Settings").font(Theme.font(40, .heavy)).foregroundStyle(Theme.text)
            HStack(alignment: .top, spacing: 40) {
                VStack(alignment: .leading, spacing: 22) {
                    row("Moonlight", model.api?.baseURL.host ?? "—")
                    row("Version", version ?? "—")
                    row("This screen", status?.display.map { "\($0.name) · \($0.layout.capitalized)" } ?? "—")
                    row("Live updates", model.connected ? "Connected" : "Reconnecting…")
                    row("Family", model.settings?.family_name ?? "—")
                    row("People", model.people.map(\.name).joined(separator: ", "))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .panel(padding: 36)

                VStack(alignment: .leading, spacing: 26) {
                    Text("Family, calendars, chores, rewards, music and photos are set up in Moonlight on your phone or a wall screen. Changes appear here straight away.")
                        .font(Theme.font(26, .bold)).foregroundStyle(Theme.muted)
                    Text("To remove this Apple TV, delete it in Settings › Screens, or forget it here and pair again.")
                        .font(Theme.font(26, .bold)).foregroundStyle(Theme.muted)
                    Button("Forget this Moonlight", role: .destructive) { confirmForget = true }
                        .buttonStyle(.pill)
                }
                .frame(width: 700, alignment: .leading)
            }
            Spacer()
        }
        .task {
            status = await model.call { try await $0.authStatus() }
            version = await model.call { try await $0.health() }?.version
        }
        .alert("Forget this Moonlight?", isPresented: $confirmForget) {
            Button("Forget", role: .destructive) { model.forget() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This Apple TV will need a new pairing code to show your family's calendar again.")
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(Theme.font(26, .bold)).foregroundStyle(Theme.muted).frame(width: 240, alignment: .leading)
            Text(value).font(Theme.font(28, .heavy)).foregroundStyle(Theme.text).lineLimit(2)
        }
    }
}
