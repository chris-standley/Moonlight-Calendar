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

    var body: some View {
        TabView {
            Tab("Today", systemImage: "sun.horizon") { TodayView() }
            Tab("Calendar", systemImage: "calendar") { CalendarView() }
            Tab("Chores", systemImage: "checkmark.circle") { ChoresView() }
            Tab("Rewards", systemImage: "star") { RewardsView() }
            Tab("Meals", systemImage: "fork.knife") { MealsView() }
            Tab("Lists", systemImage: "list.bullet") { ListsView() }
            Tab("Photos", systemImage: "photo.on.rectangle") { PhotosView() }
            Tab("Settings", systemImage: "gearshape") { SettingsView() }
        }
        .overlay { CameraPopUp() }
        .task { await model.refreshWeatherPeriodically() }
        // The remote's Play/Pause controls this screen's speaker from anywhere (Photos uses it for the slideshow).
        .onPlayPauseCommand {
            Task {
                _ = await model.call { try await $0.media("play_pause") }
                model.bump("media")
            }
        }
    }
}
