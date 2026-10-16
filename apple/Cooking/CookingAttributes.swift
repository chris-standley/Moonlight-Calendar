import ActivityKit
import Foundation

/// The Live Activity shown while following a recipe: the current step on the Lock Screen and in the Dynamic Island,
/// with the next timer counting down. Shared by the app (which starts and updates it) and the CookingWidget extension
/// (which draws it).
struct CookingAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// 1-based; 0 once every step is done.
        var step: Int
        var steps: Int
        var text: String
        var timerLabel: String?
        var timerEnds: Date?
        /// Timers that have gone off and are waiting to be stopped.
        var ringing: Int = 0
    }

    var recipe: String
    var emoji: String
}
