import SwiftUI

@main
struct MoonlightApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task { await model.start() }
                .preferredColorScheme(model.settings?.colorScheme)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.phase {
            case .starting:
                VStack(spacing: 30) {
                    LogoMark(size: 160)
                    ProgressView()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Theme.bg.ignoresSafeArea())
            case .setup:
                SetupView()
            case .ready:
                MainTabs()
            }
        }
        .animation(.easeInOut(duration: 0.35), value: model.phase)
    }
}

struct MainTabs: View {
    @Environment(AppModel.self) private var model
    @State private var nursery = false
    @State private var energy = false
    @State private var security = false
    @State private var music = false

    var body: some View {
        TabView {
            Tab("Today", systemImage: "sun.horizon") { TodayView() }
            Tab("Calendar", systemImage: "calendar") { CalendarView() }
            Tab("Chores", systemImage: "checkmark.circle") { ChoresView() }
            Tab("Rewards", systemImage: "star") { RewardsView() }
            Tab("Meals", systemImage: "fork.knife") { MealsView() }
            Tab("Lists", systemImage: "list.bullet") { ListsView() }
            // A tab builder takes at most ten entries, so the sections that come and go share one.
            Group {
                // Once Tapestry is connected in Settings › Nursery on a wall screen.
                if nursery { Tab("Nursery", systemImage: "figure.and.child.holdinghands") { NurseryView() } }
                // Once Home Assistant has an alarm or a camera to show (Settings › Security on a wall screen).
                if security { Tab("Security", systemImage: "lock.shield") { SecurityView() } }
                // Once Home Assistant has something for the house picture (Settings › Energy on a wall screen).
                if energy { Tab("Energy", systemImage: "bolt") { EnergyView() } }
                // Once this screen has a speaker (Settings › Screens on a wall screen).
                if music { Tab("Music", systemImage: "music.note") { MusicView() } }
            }
            Tab("Photos", systemImage: "photo.on.rectangle") { PhotosView() }
            Tab("Settings", systemImage: "gearshape") { SettingsView() }
        }
        .overlay { CameraPopUp() }
        .overlay { ScreenAlertsOverlay() }
        .task { await model.refreshWeatherPeriodically() }
        .task(id: model.rev("nursery")) {
            if let c = await model.call({ try await $0.nursery() }) { nursery = c.configured }
        }
        .task(id: model.rev("settings")) {
            if let e = await model.call({ try await $0.energy() }) { energy = e.configured && !e.isEmpty }
            if let s = await model.call({ try await $0.security() }) {
                security = s.configured && (s.alarm != nil || !s.cameras.isEmpty || !s.sensors.isEmpty)
            }
        }
        .task(id: model.rev("settings", "displays")) {
            if let n = await model.call({ try await $0.nowPlaying() }) { music = n.configured }
        }
        // The remote's Play/Pause controls this screen's speaker from anywhere (Photos uses it for the slideshow).
        .onPlayPauseCommand {
            Task {
                _ = await model.call { try await $0.media("play_pause") }
                model.bump("media")
            }
        }
    }
}
