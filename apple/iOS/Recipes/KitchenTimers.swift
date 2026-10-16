import AudioToolbox
import Foundation
import Observation
import UIKit
import UserNotifications

/// One countdown started from a recipe step.
struct KitchenTimer: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let recipe: String
    let total: Int
    var ends: Date
    /// Seconds left while paused (nil while running).
    var pausedLeft: TimeInterval?

    func left(at now: Date = .now) -> TimeInterval { pausedLeft ?? max(0, ends.timeIntervalSince(now)) }
    func done(at now: Date = .now) -> Bool { pausedLeft == nil && ends <= now }
}

/// Kitchen timers on this phone. Each one also books a local notification, so it goes off with the app closed or the
/// phone locked; the notification has "+1 minute" and "Stop" buttons that work without opening the app.
@Observable
@MainActor
final class KitchenTimers {
    static let shared = KitchenTimers()
    nonisolated static let category = "moonlight.kitchen-timer"
    private static let idPrefix = "timer."  // not "moonlight.": Reminders clears those when it reschedules
    private static let saved = "kitchen.timers"

    private(set) var timers: [KitchenTimer] = []
    /// Ticks twice a second while any timer is running, so countdowns redraw.
    private(set) var now = Date()
    private var ticker: Task<Void, Never>?
    private var lastChime = Date.distantPast

    init() {
        if let data = UserDefaults.standard.data(forKey: Self.saved),
           let list = try? JSONDecoder().decode([KitchenTimer].self, from: data) {
            timers = list.filter { $0.pausedLeft != nil || $0.ends > Date().addingTimeInterval(-3600) }
        }
        if !timers.isEmpty { tick() }
    }

    var ringing: [KitchenTimer] { timers.filter { $0.done(at: now) } }

    /// The "+1 minute" / "Stop" buttons on a timer's notification. Call once at launch.
    static func registerNotificationActions() {
        let more = UNNotificationAction(identifier: "add1", title: "+1 minute", options: [])
        let stop = UNNotificationAction(identifier: "stop", title: "Stop", options: [.destructive])
        let cat = UNNotificationCategory(identifier: category, actions: [more, stop], intentIdentifiers: [], options: [])
        UNUserNotificationCenter.current().setNotificationCategories([cat])
    }

    @discardableResult
    func start(_ label: String, seconds: Int, recipe: String) -> KitchenTimer {
        let t = KitchenTimer(id: UUID().uuidString, label: label, recipe: recipe, total: seconds,
                             ends: Date().addingTimeInterval(TimeInterval(seconds)))
        timers.append(t)
        changed(t)
        Task { _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) }
        return t
    }

    func stop(_ id: String) {
        timers.removeAll { $0.id == id }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [Self.idPrefix + id])
        UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: [Self.idPrefix + id])
        save()
    }

    /// Add time; on a timer that has gone off, starts it again for that long.
    func add(_ id: String, seconds: Int) {
        guard let i = timers.firstIndex(where: { $0.id == id }) else { return }
        if let left = timers[i].pausedLeft {
            timers[i].pausedLeft = left + TimeInterval(seconds)
        } else {
            timers[i].ends = max(timers[i].ends, Date()).addingTimeInterval(TimeInterval(seconds))
        }
        changed(timers[i])
    }

    func togglePause(_ id: String) {
        guard let i = timers.firstIndex(where: { $0.id == id }), !timers[i].done() else { return }
        if let left = timers[i].pausedLeft {
            timers[i].ends = Date().addingTimeInterval(left)
            timers[i].pausedLeft = nil
        } else {
            timers[i].pausedLeft = timers[i].left()
        }
        changed(timers[i])
    }

    func running(label: String, recipe: String) -> Bool {
        timers.contains { $0.label == label && $0.recipe == recipe && !$0.done(at: now) }
    }

    /// A tap on a timer notification's button, possibly with the app woken in the background just for this.
    func handle(action: String, userInfo: [String: String]) {
        guard let id = userInfo["timer"], !id.isEmpty else { return }
        switch action {
        case "add1":
            if timers.contains(where: { $0.id == id }) {
                add(id, seconds: 60)
            } else {
                start(userInfo["label"] ?? "Timer", seconds: 60, recipe: userInfo["recipe"] ?? "")
            }
        case "stop":
            stop(id)
        default:
            break
        }
    }

    // MARK: -

    private func changed(_ t: KitchenTimer) {
        schedule(t)
        save()
        tick()
        CookingLiveActivity.shared.timersChanged()
    }

    private func schedule(_ t: KitchenTimer) {
        let center = UNUserNotificationCenter.current()
        let id = Self.idPrefix + t.id
        center.removePendingNotificationRequests(withIdentifiers: [id])
        guard t.pausedLeft == nil, t.ends > Date() else { return }
        let content = UNMutableNotificationContent()
        content.title = "⏱ \(t.label)"
        content.body = t.recipe.isEmpty ? "Time's up" : "\(t.recipe): time's up"
        content.sound = .default
        content.categoryIdentifier = Self.category
        content.interruptionLevel = .timeSensitive
        content.threadIdentifier = "kitchen-timers"
        content.userInfo = ["timer": t.id, "label": t.label, "recipe": t.recipe]
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, t.ends.timeIntervalSinceNow), repeats: false)
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: trigger))
    }

    private func save() {
        if let data = try? JSONEncoder().encode(timers) { UserDefaults.standard.set(data, forKey: Self.saved) }
    }

    private func tick() {
        guard ticker == nil else { return }
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, !self.timers.isEmpty else { break }
                self.now = Date()
                // Chime in the app while one has gone off (the notification sounds when the app is closed).
                if !self.ringing.isEmpty, UIApplication.shared.applicationState == .active,
                   self.now.timeIntervalSince(self.lastChime) > 2.5 {
                    self.lastChime = self.now
                    AudioServicesPlayAlertSound(SystemSoundID(1005))
                }
                try? await Task.sleep(for: .milliseconds(500))
            }
            self?.ticker = nil
        }
    }
}

/// Shows notifications while the app is open, and runs the timer buttons. Set as the notification centre's delegate
/// at launch.
final class NotificationHandler: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationHandler()

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async
        -> UNNotificationPresentationOptions {
        // A timer going off with the app open chimes in the app already; keep it in Notification Centre only.
        notification.request.content.categoryIdentifier == KitchenTimers.category ? [.list] : [.banner, .sound, .list]
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let content = response.notification.request.content
        guard content.categoryIdentifier == KitchenTimers.category else { return }
        let action = response.actionIdentifier
        let info = content.userInfo
        let sendable = ["timer": info["timer"] as? String ?? "", "label": info["label"] as? String ?? "",
                        "recipe": info["recipe"] as? String ?? ""]
        await MainActor.run { KitchenTimers.shared.handle(action: action, userInfo: sendable) }
    }
}
