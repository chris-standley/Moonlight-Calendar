import ActivityKit
import Foundation

/// Starts, updates and ends the cooking Live Activity (drawn by the CookingWidget extension) while cook mode is open,
/// so the current step and the next timer show on the Lock Screen and in the Dynamic Island.
@MainActor
final class CookingLiveActivity {
    static let shared = CookingLiveActivity()

    private var activity: Activity<CookingAttributes>?
    private var recipe = ""
    private var state: CookingAttributes.ContentState?

    func begin(_ r: Recipe) {
        endAll()
        recipe = r.title
        state = nil
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let first = r.steps.first?.shown ?? ""
        let s = CookingAttributes.ContentState(step: 1, steps: r.steps.count, text: first)
        state = s
        activity = try? Activity.request(attributes: CookingAttributes(recipe: r.title, emoji: r.emoji),
                                         content: .init(state: withTimer(s), staleDate: nil), pushType: nil)
    }

    /// The step on screen (index past the last step = the "all done" page).
    func show(step index: Int, of count: Int, text: String) {
        guard state != nil else { return }
        state = CookingAttributes.ContentState(step: index < count ? index + 1 : 0, steps: count, text: text)
        push()
    }

    func timersChanged() { push() }

    func end() {
        endAll()
        state = nil
    }

    private func withTimer(_ s: CookingAttributes.ContentState) -> CookingAttributes.ContentState {
        var s = s
        let mine = KitchenTimers.shared.timers.filter { $0.recipe == recipe }
        let next = mine.filter { $0.pausedLeft == nil && $0.ends > Date() }.min { $0.ends < $1.ends }
        s.timerLabel = next?.label
        s.timerEnds = next?.ends
        s.ringing = mine.filter { $0.done() }.count
        return s
    }

    private func push() {
        guard let s = state, let activity else { return }
        let content = ActivityContent(state: withTimer(s), staleDate: nil)
        Task { await activity.update(content) }
    }

    private func endAll() {
        activity = nil
        for a in Activity<CookingAttributes>.activities {
            Task { await a.end(nil, dismissalPolicy: .immediate) }
        }
    }
}
