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
                .preferredColorScheme(model.settings?.colorScheme)
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
    @AppStorage(AppTab.orderKey) private var order = ""

    var body: some View {
        TabView(selection: $tab) {
            ForEach(AppTab.ordered(order)) { t in
                Tab(t.title, systemImage: t.symbol, value: t.rawValue) { t.screen }
            }
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

/// The app's tabs. On iPhone the first four fit in the tab bar and the rest go under More; the order is chosen in
/// Settings › Tab bar and kept on this device.
enum AppTab: String, CaseIterable, Identifiable {
    case today, calendar, chores, rewards, meals, recipes, lists, settings

    static let orderKey = "tabs.order"
    var id: String { rawValue }

    var title: String { rawValue == "today" ? "Today" : rawValue.prefix(1).uppercased() + rawValue.dropFirst() }

    var symbol: String {
        switch self {
        case .today: "sun.horizon"
        case .calendar: "calendar"
        case .chores: "checkmark.circle"
        case .rewards: "star"
        case .meals: "fork.knife"
        case .recipes: "book.closed"
        case .lists: "list.bullet"
        case .settings: "gearshape"
        }
    }

    @MainActor @ViewBuilder
    var screen: some View {
        switch self {
        case .today: TodayScreen()
        case .calendar: CalendarScreen()
        case .chores: ChoresScreen()
        case .rewards: RewardsScreen()
        case .meals: MealsScreen()
        case .recipes: RecipesScreen()
        case .lists: ListsScreen()
        case .settings: SettingsScreen()
        }
    }

    /// The saved order ("meals,today,…"), with any tab it doesn't name added at the end in the usual order.
    static func ordered(_ saved: String) -> [AppTab] {
        var out: [AppTab] = []
        for id in saved.split(separator: ",") {
            if let t = AppTab(rawValue: String(id)), !out.contains(t) { out.append(t) }
        }
        return out + allCases.filter { !out.contains($0) }
    }
}
