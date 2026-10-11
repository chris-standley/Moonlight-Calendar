import SwiftUI

@main
struct MoonlightApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task { await model.start() }
                .tint(Theme.accent)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.phase {
            case .starting:
                VStack(spacing: 20) {
                    LogoMark(size: 96)
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
        .animation(.easeInOut(duration: 0.3), value: model.phase)
    }
}

/// A tab bar on iPhone (and a folded or narrow window); a sidebar on iPad and other wide windows,
/// which people can collapse back into a tab bar. The system switches as the width changes.
struct MainTabs: View {
    @Environment(AppModel.self) private var model
    @SceneStorage("tab") private var tab = "today"

    var body: some View {
        TabView(selection: $tab) {
            Tab("Today", systemImage: "sun.horizon", value: "today") { TodayScreen() }
            Tab("Calendar", systemImage: "calendar", value: "calendar") { CalendarScreen() }
            Tab("Chores", systemImage: "checkmark.circle", value: "chores") { ChoresScreen() }
            Tab("Rewards", systemImage: "star", value: "rewards") { RewardsScreen() }
            Tab("Meals", systemImage: "fork.knife", value: "meals") { MealsScreen() }
            Tab("Lists", systemImage: "list.bullet", value: "lists") { ListsScreen() }
            Tab("Settings", systemImage: "gearshape", value: "settings") { SettingsScreen() }
        }
        .tabViewStyle(.sidebarAdaptable)
        .task { await model.refreshWeatherPeriodically() }
    }
}
