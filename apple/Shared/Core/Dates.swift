import Foundation

/// Date helpers on the API's naive strings, in the household's timezone (settings.timezone), like frontend/src/dates.ts.
struct Dates {
    let calendar: Calendar

    init(timezone: String?) {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = timezone.flatMap(TimeZone.init(identifier:)) ?? .current
        cal.locale = Locale(identifier: "en_GB")
        calendar = cal
    }

    private func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.calendar = calendar
        f.timeZone = calendar.timeZone
        f.locale = Locale(identifier: "en_GB")
        f.dateFormat = format
        return f
    }

    func iso(_ d: Date) -> String { formatter("yyyy-MM-dd").string(from: d) }
    func isoDT(_ d: Date) -> String { formatter("yyyy-MM-dd'T'HH:mm").string(from: d) }
    func date(_ s: String) -> Date {
        let f = formatter(s.count > 10 ? "yyyy-MM-dd'T'HH:mm" : "yyyy-MM-dd")
        return f.date(from: String(s.prefix(16))) ?? Date()
    }

    var today: String { iso(Date()) }
    var now: String { isoDT(Date()) }

    func addDays(_ s: String, _ n: Int) -> String {
        iso(calendar.date(byAdding: .day, value: n, to: date(s)) ?? Date())
    }

    func days(from start: String, count: Int) -> [String] { (0..<count).map { addDays(start, $0) } }

    /// Monday or Sunday on or before `s`.
    func weekStart(_ s: String, start: String) -> String {
        let weekday = calendar.component(.weekday, from: date(s)) // 1 = Sunday
        let back = start == "sunday" ? weekday - 1 : (weekday + 5) % 7
        return addDays(s, -back)
    }

    func dow(_ s: String) -> String { formatter("EEE").string(from: date(s)).uppercased() }
    func dowLong(_ s: String) -> String { formatter("EEEE").string(from: date(s)) }
    func dayNum(_ s: String) -> String { String(calendar.component(.day, from: date(s))) }
    func dayMonth(_ s: String) -> String { formatter("d MMM").string(from: date(s)) }
    func longDate(_ d: Date) -> String { formatter("EEEE d MMMM").string(from: d) }

    /// "9am", "8:30pm" as the wall screens write times.
    func time(_ s: String) -> String {
        let parts = s.dropFirst(11).prefix(5).split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return "" }
        let (h, m) = (parts[0], parts[1])
        let ap = h < 12 ? "am" : "pm"
        let h12 = h % 12 == 0 ? 12 : h % 12
        return m == 0 ? "\(h12)\(ap)" : String(format: "%d:%02d%@", h12, m, ap)
    }

    func clock(_ d: Date) -> String { time(isoDT(d)) }

    func range(_ o: Occurrence) -> String {
        if o.all_day { return "All day" }
        return "\(time(o.start)) – \(time(o.end))"
    }

    /// "Today", "Tomorrow", else "Wednesday 14 Oct".
    func relative(_ s: String) -> String {
        if s == today { return "Today" }
        if s == addDays(today, 1) { return "Tomorrow" }
        return formatter("EEEE d MMM").string(from: date(s))
    }

    /// Does the occurrence touch day `d` (end exclusive)?
    func overlaps(_ o: Occurrence, day d: String) -> Bool {
        let next = addDays(d, 1) + "T00:00"
        return o.start < next && o.end > d + "T00:00" || (o.start == o.end && o.startDay == d)
    }
}
