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
    /// "light", "dark", or "auto" (follow the device), chosen in Settings > Display > Appearance.
    var theme: String?
    var pin_set: Bool
    var timezone: String?
    var screensaver_seconds: Int?
    /// Show when and where each photo was taken (default true).
    var photo_details: Bool?
    var media_players: [String: String]?
    var security: SecuritySettings?
}

/// The part of Settings › Security the apps use: which styles of screen pop up a camera that sees a person.
struct SecuritySettings: Codable {
    var popup: [String: Bool]?
}

/// A camera that sees a person now (`/api/security/alerts`). `video_hd_url` is its full-resolution HLS video.
struct SecurityAlert: Codable, Identifiable, Equatable {
    let camera: String
    let name: String
    let test: Bool
    let snapshot_url: String
    let video_url: String?
    let video_hd_url: String?
    var id: String { camera }
}

struct Repeat: Codable, Hashable {
    let freq: String
    let interval: Int
    let byday: [String]?
    let until: String?
    let skip_holidays: Bool?
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
    var skip_holidays: Bool? = nil

    var json: [String: Any] {
        var out: [String: Any] = ["type": type]
        if type == "weekly" { out["days"] = days ?? [] }
        if type == "once", let date { out["date"] = date }
        if type != "once" && skip_holidays == true { out["skip_holidays"] = true }
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
    struct Day: Codable, Hashable {
        let date: String; let high: Int; let low: Int; let condition: String
        /// Chance of rain or snow in percent; nil when the weather source doesn't say.
        let rain: Int?
    }
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
    /// Local time where it was taken, written with a Z: its digits are used as they are.
    var taken_at: String? = nil
    /// The Home Assistant zone it was taken in ("Home"), or the town.
    var place: String? = nil

    /// "14 July 2025 · 3:30pm", or nil when Immich doesn't know.
    var takenText: String? {
        var parts: [String] = []
        let digits = taken_at.map { String($0.prefix(16)) } ?? ""
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd'T'HH:mm"
        if let d = parser.date(from: digits) {
            let out = DateFormatter()
            out.locale = Locale(identifier: "en_GB")
            out.dateFormat = "d MMMM yyyy"
            parts.append(out.string(from: d))
            out.dateFormat = Calendar.current.component(.minute, from: d) == 0 ? "ha" : "h:mma"
            out.amSymbol = "am"
            out.pmSymbol = "pm"
            parts.append(out.string(from: d))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
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
    /// A random id per install (0.4.0+), so one Moonlight found under several names is listed once.
    let instance: String?
    /// Moonlight's https address from the internet (add-on option), if set.
    let external_url: String?
    /// Whether "Sign in with Home Assistant" is available.
    let ha_login: Bool?
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
