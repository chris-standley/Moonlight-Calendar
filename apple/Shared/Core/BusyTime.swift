import Foundation

// Work-calendar free/busy blocks, folded the way the wall screens show them: per set of people per day, one line with
// the first start, the last finish, the free gaps and anything tentative, instead of a card per meeting.

extension Occurrence {
    /// A timed busy/tentative block from a published free/busy calendar.
    var isBusyBlock: Bool { busy != nil && busy != "free" && !all_day }
}

struct BusyRun: Hashable {
    var start: Int  // minutes from midnight
    var end: Int
    var tentative: Bool
}

/// One person's (or one set of people's) busy time on one day.
struct BusyDay: Hashable, Identifiable {
    let personIds: [String]
    let runs: [BusyRun]
    /// The colour of the calendar the blocks came from.
    let color: String?
    var id: String { personIds.joined(separator: ",") }
    var start: Int { runs.first?.start ?? 0 }
    var end: Int { runs.last?.end ?? 0 }
    var allTentative: Bool { runs.allSatisfy(\.tentative) }

    /// Free gaps of 15 minutes or more between the runs.
    var gaps: [(Int, Int)] {
        zip(runs, runs.dropFirst()).compactMap { a, b in b.start - a.end >= 15 ? (a.end, b.start) : nil }
    }

    func who(_ people: [Person]) -> String {
        let names = personIds.compactMap { id in people.first { $0.id == id }?.name }
        return (names.isEmpty ? "Busy" : "\(names.joined(separator: " & ")) busy") + (allTentative ? " (tentative)" : "")
    }

    /// "Free 12–1pm, 3:30–4pm" and "Tentative 2–3pm", for the line under the title.
    func details(_ d: Dates) -> [String] {
        let free = gaps.isEmpty ? "No gaps" : "Free " + gaps.map { d.span($0.0, $0.1) }.joined(separator: ", ")
        let tentative = runs.filter(\.tentative)
        guard !tentative.isEmpty && !allTentative else { return [free] }
        return [free, "Tentative " + tentative.map { d.span($0.start, $0.end) }.joined(separator: ", ")]
    }

    /// Merge one day's busy blocks per set of people. Overlapping blocks show once; busy wins over tentative.
    static func make(_ events: [Occurrence], day: String) -> [BusyDay] {
        let blocks = events.filter(\.isBusyBlock)
        let groups = Dictionary(grouping: blocks) { $0.person_ids.sorted().joined(separator: ",") }
        return groups.values.compactMap { occs -> BusyDay? in
            let runs = Self.runs(occs, day: day)
            guard !runs.isEmpty else { return nil }
            return BusyDay(personIds: occs[0].person_ids.sorted(), runs: runs, color: occs[0].color)
        }
        .sorted { ($0.start, $0.id) < ($1.start, $1.id) }
    }

    private static func runs(_ occs: [Occurrence], day: String) -> [BusyRun] {
        struct Seg { let s: Int; let e: Int; let t: Bool }
        let segs = occs.map { o in
            Seg(s: o.startDay < day ? 0 : minutes(o.start),
                e: String(o.end.prefix(10)) > day ? 24 * 60 : minutes(o.end),
                t: o.busy == "tentative")
        }.filter { $0.e > $0.s }
        let cuts = Array(Set(segs.flatMap { [$0.s, $0.e] })).sorted()
        var out: [BusyRun] = []
        for (a, b) in zip(cuts, cuts.dropFirst()) {
            let on = segs.filter { $0.s < b && $0.e > a }
            guard !on.isEmpty else { continue }
            let tentative = on.allSatisfy(\.t)
            if var last = out.last, last.end == a, last.tentative == tentative {
                last.end = b
                out[out.count - 1] = last
            } else {
                out.append(BusyRun(start: a, end: b, tentative: tentative))
            }
        }
        return out
    }

    private static func minutes(_ s: String) -> Int {
        let parts = s.dropFirst(11).prefix(5).split(separator: ":").compactMap { Int($0) }
        return parts.count == 2 ? parts[0] * 60 + parts[1] : 0
    }
}

/// What a day's list shows: events, with busy blocks folded into one line per person.
enum AgendaItem: Identifiable, Hashable {
    case event(Occurrence)
    case busy(BusyDay)

    var id: String {
        switch self {
        case .event(let o): o.key
        case .busy(let b): "busy:" + b.id
        }
    }

    /// All-day events first, then everything else by start time.
    static func make(_ events: [Occurrence], day: String) -> [AgendaItem] {
        let dayEvents = events.filter { !$0.isBusyBlock }
        let allDay = dayEvents.filter(\.all_day).sorted { $0.start < $1.start }.map(AgendaItem.event)
        let timed: [(Int, String, AgendaItem)] = dayEvents.filter { !$0.all_day }.map { o in
            (o.startDay < day ? 0 : BusyDay.startMinutes(o.start), o.start, .event(o))
        } + BusyDay.make(events, day: day).map { ($0.start, "", .busy($0)) }
        return allDay + timed.sorted { ($0.0, $0.1) < ($1.0, $1.1) }.map(\.2)
    }
}

extension BusyDay {
    fileprivate static func startMinutes(_ s: String) -> Int { minutes(s) }
}

extension Dates {
    /// Minutes from midnight as "9am" / "5:30pm".
    func clock(minutes m: Int) -> String {
        let m = m % (24 * 60)  // a block running to midnight ends at 12am
        return time(String(format: "2000-01-01T%02d:%02d", m / 60, m % 60))
    }

    func span(_ a: Int, _ b: Int) -> String { "\(clock(minutes: a))–\(clock(minutes: b))" }
}

// MARK: Chores due now

extension ChoreDay {
    private static let order = ["morning", "afternoon", "evening"]

    /// Morning until noon, afternoon until 5pm, then evening (household time).
    static func period(_ d: Dates, at date: Date = Date()) -> String {
        let h = d.calendar.component(.hour, from: date)
        return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"
    }

    /// Unfinished chores for now: earlier ones still not done first, then this part of the day, then "anytime".
    static func dueNow(_ chores: [ChoreDay], period: String) -> [ChoreDay] {
        let upTo = order.prefix((order.firstIndex(of: period) ?? 2) + 1)
        func rank(_ c: ChoreDay) -> Int { c.time_of_day == "anytime" ? 3 : order.firstIndex(of: c.time_of_day) ?? 3 }
        return chores.filter { !$0.completed && ($0.time_of_day == "anytime" || upTo.contains($0.time_of_day)) }
            .enumerated().sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }.map(\.element)
    }
}
