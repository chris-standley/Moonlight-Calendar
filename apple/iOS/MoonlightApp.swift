import SwiftUI
import UserNotifications

@main
struct MoonlightApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        UNUserNotificationCenter.current().delegate = NotificationHandler.shared
        KitchenTimers.registerNotificationActions()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task { await model.start() }
                .tint(Theme.accent)
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .background, let api = model.api else { return }
            Reminders.scheduleRefresh()
            Task { await Reminders.reschedule(api) }
        }
        .backgroundTask(.appRefresh(Reminders.refreshTask)) { await Reminders.backgroundRefresh() }
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

/// A tab bar everywhere by default (floating at the top on iPad, as iPadOS places it). On iPad the tab bar's
/// sidebar button switches to a sidebar and back; the system remembers the choice.
struct MainTabs: View {
    @Environment(AppModel.self) private var model
    @SceneStorage("tab") private var tab = "today"

    var body: some View {
        TabView(selection: $tab) {
            Tab("Today", systemImage: "sun.horizon", value: "today") { TodayScreen() }
            Tab("Calendar", systemImage: "calendar", value: "calendar") { CalendarScreen() }
            Tab("Chores", systemImage: "checkmark.circle", value: "chores") { ChoresScreen() }
            Tab("Rewards", systemImage: "star", value: "rewards") { RewardsScreen() }
            Tab("Meals", systemImage: "fork.knife", value: "meals") { MealsTab() }
            Tab("Lists", systemImage: "list.bullet", value: "lists") { ListsScreen() }
            Tab("Settings", systemImage: "gearshape", value: "settings") { SettingsScreen() }
        }
        .tabViewStyle(.sidebarAdaptable)
        .defaultAdaptableTabBarPlacement(.tabBar)
        .task { await model.refreshWeatherPeriodically() }
        // Keep reminders and Siri's list of people and lists in step with the family's data.
        .task(id: model.rev("events", "chores", "people", "settings", "reminders")) {
            if let api = model.api { await Reminders.reschedule(api) }
        }
        .task(id: model.rev("people", "lists")) { MoonlightShortcuts.updateAppShortcutParameters() }
    }
}
