import BackgroundTasks
import Foundation
import UserNotifications

/// Local notifications before events and an evening nudge about chores left. They are worked out on this device from
/// the calendar and rescheduled whenever it changes, when the app goes to the background, and on background refresh.
enum Reminders {
    static let refreshTask = "io.github.chris-standley.moonlight.refresh"
    private static let idPrefix = "moonlight."
    private static let maxEvents = 50  // iOS keeps 64 pending notifications per app

    // Settings (Settings › Reminders), shared with @AppStorage.
    enum Key {
        static let events = "reminders.events"
        static let lead = "reminders.lead"          // minutes before the start
        static let people = "reminders.people"      // comma-separated person ids; empty = everyone
        static let chores = "reminders.chores"
        static let choresAt = "reminders.choresAt"  // minutes after midnight
    }
    static let leadChoices = [5, 10, 15, 30, 60, 120]
    static let defaultLead = 15
    static let defaultChoresAt = 18 * 60

    private static var defaults: UserDefaults { .standard }
    static var anyOn: Bool { defaults.bool(forKey: Key.events) || defaults.bool(forKey: Key.chores) }

    static func requestPermission() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    /// Replace every pending Moonlight reminder with ones for the next few days.
    static func reschedule(_ api: APIClient) async {
        let center = UNUserNotificationCenter.current()
        let pending = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(idPrefix) }
        guard anyOn else {
            center.removePendingNotificationRequests(withIdentifiers: pending)
            return
        }
        guard await center.notificationSettings().authorizationStatus == .authorized,
              let people = try? await api.people() else { return }
        let d = Dates(timezone: (try? await api.settings())?.timezone)
        var requests: [UNNotificationRequest] = []
        if defaults.bool(forKey: Key.events), let events = try? await api.events(d.today, d.addDays(d.today, 4)) {
            requests += eventReminders(events, people: people, dates: d)
        }
        if defaults.bool(forKey: Key.chores), let chores = try? await api.chores(d.today) {
            requests += choreReminder(chores, people: people, dates: d)
        }
        center.removePendingNotificationRequests(withIdentifiers: pending)
        for r in requests { try? await center.add(r) }
    }

    private static func eventReminders(_ events: [Occurrence], people: [Person], dates d: Dates) -> [UNNotificationRequest] {
        let lead = defaults.object(forKey: Key.lead) as? Int ?? defaultLead
        let only = Set((defaults.string(forKey: Key.people) ?? "").split(separator: ",").map(String.init))
        let now = Date()
        return events
            .filter { !$0.all_day && $0.busy == nil }
            .filter { only.isEmpty || !only.isDisjoint(with: $0.person_ids) }
            .map { (event: $0, fire: d.date($0.start).addingTimeInterval(TimeInterval(-lead * 60))) }
            .filter { $0.fire > now }
            .sorted { $0.fire < $1.fire }
            .prefix(maxEvents)
            .map { item in
                let e = item.event
                let content = UNMutableNotificationContent()
                content.title = e.displayTitle(people)
                let names = e.person_ids.compactMap { id in people.first { $0.id == id }?.name }
                content.body = ([d.range(e)] + [names.joined(separator: ", "), e.location ?? ""])
                    .filter { !$0.isEmpty }.joined(separator: " · ")
                content.sound = .default
                content.threadIdentifier = "events"
                let trigger = UNTimeIntervalNotificationTrigger(timeInterval: item.fire.timeIntervalSince(now), repeats: false)
                return UNNotificationRequest(identifier: "\(idPrefix)event.\(e.occurrence_id)", content: content, trigger: trigger)
            }
    }

    private static func choreReminder(_ chores: [ChoreDay], people: [Person], dates d: Dates) -> [UNNotificationRequest] {
        let at = defaults.object(forKey: Key.choresAt) as? Int ?? defaultChoresAt
        let fire = d.date(String(format: "%@T%02d:%02d", d.today, at / 60, at % 60))
        guard fire > Date() else { return [] }
        let left = people.compactMap { p -> String? in
            let n = chores.filter { $0.person_id == p.id && !$0.completed }.count
            return n == 0 ? nil : "\(p.name) \(n)"
        }
        guard !left.isEmpty else { return [] }
        let content = UNMutableNotificationContent()
        content.title = "Chores left today"
        content.body = left.joined(separator: ", ")
        content.sound = .default
        content.threadIdentifier = "chores"
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: fire.timeIntervalSinceNow, repeats: false)
        return [UNNotificationRequest(identifier: "\(idPrefix)chores.\(d.today)", content: content, trigger: trigger)]
    }

    // MARK: Background refresh

    /// Ask iOS to wake the app now and then, so reminders follow changes made on other screens.
    static func scheduleRefresh() {
        guard anyOn else { return }
        let request = BGAppRefreshTaskRequest(identifier: refreshTask)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 2 * 3600)
        try? BGTaskScheduler.shared.submit(request)
    }

    /// The background refresh itself: reschedule with the stored pairing.
    static func backgroundRefresh() async {
        scheduleRefresh()
        guard let token = Credentials.token, let server = await Credentials.reachableServer() else { return }
        await reschedule(APIClient(baseURL: server, token: token))
    }
}
