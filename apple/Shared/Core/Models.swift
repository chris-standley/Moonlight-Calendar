import Foundation

// Types mirror API.md. Times are household-local naive strings ("2026-10-12T09:00"), dates "YYYY-MM-DD".

struct Person: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let initials: String
    let color: String
    let role: String
    let sort: Int

    var isChild: Bool { role == "child" }
}

struct Settings: Codable {
    var family_name: String
    var week_start: String
    var temp_unit: String
    var pin_set: Bool
    var timezone: String?
    var screensaver_seconds: Int?
    var media_players: [String: String]?
}

struct Repeat: Codable, Hashable {
    let freq: String
    let interval: Int
    let byday: [String]?
    let until: String?
}

struct Occurrence: Codable, Identifiable, Hashable {
    let id: String
    let occurrence_id: String
    let title: String
    let person_ids: [String]
    let start: String
    let end: String
    let all_day: Bool
    let location: String?
    let notes: String?
    let `repeat`: Repeat?
    let recurring: Bool?
    let custom_repeat: Bool?
    let color: String?
    let busy: String?
    let read_only: Bool?
    let calendar_id: String?

    var key: String { occurrence_id }
    var editable: Bool { read_only != true && busy == nil }
    var startDay: String { String(start.prefix(10)) }
}

struct ChoreDay: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let emoji: String
    let person_id: String
    let points: Int
    let time_of_day: String
    let sort: Int
    let schedule: ChoreSchedule
    let date: String
    var completed: Bool
    let streak: Int
}

/// `{type: "daily"}` | `{type: "weekly", days: ["MO",..]}` | `{type: "once", date}`
struct ChoreSchedule: Codable, Hashable {
    var type: String
    var days: [String]?
    var date: String?

    var json: [String: Any] {
        var out: [String: Any] = ["type": type]
        if type == "weekly" { out["days"] = days ?? [] }
        if type == "once", let date { out["date"] = date }
        return out
    }
}

struct Balance: Codable, Hashable {
    let person_id: String
    let balance: Int
}

struct Reward: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let emoji: String
    let cost: Int
    let person_id: String?
}

struct LedgerEntry: Codable, Identifiable, Hashable {
    let id: String
    let person_id: String
    let change: Int
    let reason: String
    let at: String
}

struct TaskList: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let emoji: String
    let color: String
    let kind: String
    let sort: Int
    let open_count: Int
    let done_count: Int
}

struct ListItem: Codable, Identifiable, Hashable {
    let id: String
    let list_id: String
    let title: String
    var done: Bool
    let person_id: String?
    let due: String?
}

struct Meal: Codable, Identifiable, Hashable {
    let id: String
    let date: String
    let slot: String
    let title: String
    let notes: String?
    let recipe_id: String?
}

struct Weather: Codable {
    struct Current: Codable { let temp: Int; let condition: String }
    struct Day: Codable, Hashable { let date: String; let high: Int; let low: Int; let condition: String }
    let current: Current
    let daily: [Day]

    func day(_ date: String) -> Day? { daily.first { $0.date == date } }
}

struct NowPlaying: Codable, Equatable {
    struct Supports: Codable, Equatable {
        let play_pause: Bool
        let previous: Bool
        let next: Bool
    }
    let configured: Bool
    let state: String
    let show: Bool
    let title: String?
    let artist: String?
    let album: String?
    let name: String?
    let art_url: String?
    let supports: Supports?

    var isPlaying: Bool { state == "playing" || state == "buffering" }
}

struct Photo: Codable, Identifiable, Hashable {
    let id: String
    let url: String
}

struct PhotoList: Codable {
    let source: String
    let photos: [Photo]
}

struct Display: Codable, Hashable {
    let id: String
    let name: String
    let layout: String
}

struct AuthStatus: Codable {
    let required: Bool
    let authorised: Bool
    let display: Display?
}

struct PairStart: Codable {
    let pair_id: String
    let code: String
    let expires_in: Int
}

struct PairPoll: Codable {
    let status: String
    let token: String?
    let expires_in: Int?
}

struct Health: Codable {
    let ok: Bool
    let version: String?
}

struct OkResponse: Codable { let ok: Bool? }
struct BalanceResponse: Codable { let balance: Int }

/// Meal slots in display order, as the wall screens show them.
enum MealSlot: String, CaseIterable, Identifiable {
    case breakfast, lunch, dinner, snack
    var id: String { rawValue }
    var label: String { rawValue.capitalized }
    var emoji: String {
        switch self {
        case .breakfast: "🥣"
        case .lunch: "🥪"
        case .dinner: "🍽️"
        case .snack: "🍎"
        }
    }
}

enum TimeOfDay: String, CaseIterable {
    case morning, afternoon, evening, anytime
    var label: String { rawValue.uppercased() }
    var emoji: String {
        switch self {
        case .morning: "🌅"
        case .afternoon: "☀️"
        case .evening: "🌙"
        case .anytime: "✨"
        }
    }
}
