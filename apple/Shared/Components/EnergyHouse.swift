import SwiftUI
import UIKit

/// The Energy picture (as on the wall screens): a house with solar on the roof, the battery inside, the grid, the car
/// and the heat pump around it, with dots running along the lines as power flows. Drawn in a 1000 × 600 space and
/// scaled to fit. `compact` keeps only the headline numbers on the picture (a phone shows the rest in cards below).
struct EnergyHouse: View {
    let data: EnergyOverview
    var compact = false
    /// The weather now: its icon takes the sun's place unless it's sunny.
    var sky: Weather.Current? = nil
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        GeometryReader { geo in
            let s = geo.size.width / 1000
            ZStack(alignment: .topLeading) {
                TimelineView(.animation) { tl in
                    Canvas { ctx, _ in
                        ctx.scaleBy(x: s, y: s)
                        EnergyScene(data: data, time: tl.date.timeIntervalSinceReferenceDate, drawSun: drawSun).draw(&ctx)
                    }
                }
                if !drawSun, let sky {
                    WeatherGlyph(condition: sky.condition, size: 120 * s)
                        .frame(width: 1, height: 1)
                        .position(x: 120 * s, y: 96 * s)
                }
                tags(s)
                chips(s)
            }
        }
        .aspectRatio(10 / 6, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        // After sunset the picture goes dark, whatever the app's own appearance.
        .environment(\.colorScheme, data.sun?.night == true ? .dark : scheme)
        .accessibilityElement(children: .combine)
    }

    private var drawSun: Bool { sky == nil || sky?.condition == "sunny" }

    @ViewBuilder
    private func tags(_ s: CGFloat) -> some View {
        if !compact {
            let t = data.temperatures
            if let v = t?.inside { tag(s, 642, 346, "Inside", Energy.degrees(v)) }
            if let v = t?.tank { tag(s, 642, 430, "Tank", Energy.degrees(v)) }
        }
    }

    private func tag(_ s: CGFloat, _ x: CGFloat, _ y: CGFloat, _ title: String, _ value: String) -> some View {
        let size = max(12 * s, 9)
        return VStack(spacing: 0) {
            Text(title.uppercased()).font(.system(size: size * 0.8, weight: .heavy, design: .rounded))
                .tracking(size * 0.05).foregroundStyle(Theme.muted)
            Text(value).font(.system(size: size * 1.35, weight: .heavy, design: .rounded)).foregroundStyle(Theme.text)
        }
        .padding(.horizontal, size * 0.6)
        .padding(.vertical, size * 0.3)
        .fixedSize()
        .background(Theme.surface.opacity(0.92), in: RoundedRectangle(cornerRadius: size * 0.7, style: .continuous))
        .shadow(color: .black.opacity(0.08), radius: 6, y: 2)
        .frame(width: 1, height: 1)
        .position(x: x * s, y: y * s)
    }

    @ViewBuilder
    private func chips(_ s: CGFloat) -> some View {
        let d = data
        if let solar = d.solar {
            chip(s, 185, 96, .leading, EnergyColors.solar, "Solar", Energy.solarValue(solar, short: compact),
                 compact ? [] : Energy.solarLines(solar))
        }
        if let b = d.battery {
            chip(s, compact ? 338 : 342, compact ? 352 : 362, .leading, EnergyColors.battery, "Battery",
                 b.soc.map { "\(Int($0.rounded()))%" } ?? "–", [compact ? nil : Energy.batteryLine(b)])
        }
        if let h = d.home {
            chip(s, compact ? 610 : 510, compact ? 125 : 128, .center, Theme.accent, compact ? "Home" : "Home is using",
                 Energy.watts(h.power), [compact ? nil : h.today.map { "\(Energy.kwh($0)) today" }])
        }
        if let g = d.grid {
            chip(s, compact ? 990 : 985, compact ? 160 : 150, .trailing, EnergyColors.grid, "Grid", Energy.gridValue(g, short: compact),
                 compact ? [] : [g.import_today.map { "\(Energy.kwh($0)) bought today" }, g.export_today.map { "\(Energy.kwh($0)) sold today" }])
        }
        if let c = d.car {
            chip(s, compact ? 120 : 135, compact ? 300 : 330, .center, EnergyColors.car, "Car", Energy.carValue(c),
                 [c.soc.map { soc in "\(Int(soc.rounded()))%" + (!compact ? c.range.map { " · \(Int($0.rounded())) \(c.range_unit ?? "")" } ?? "" : "") },
                  compact ? nil : (c.charging == true ? "Charging" : nil),
                  compact ? nil : c.session.flatMap { $0 > 0 ? "\(Energy.kwh($0)) added" : nil },
                  compact ? nil : Energy.carTarget(c)])
        }
        if let hp = d.heat_pump {
            chip(s, compact ? 800 : 712, compact ? 375 : 370, compact ? .center : .leading, EnergyColors.heat, "Heat pump",
                 compact ? (hp.running ? Energy.watts(hp.power) : "Idle") : (hp.running ? hp.doing : "Idle"),
                 compact ? [Energy.heatPumpShort(hp)] : Energy.heatPumpLines(hp))
        }
    }

    private func chip(_ s: CGFloat, _ x: CGFloat, _ y: CGFloat, _ align: Alignment, _ tint: Color, _ title: String,
                      _ value: String, _ lines: [String?]) -> some View {
        let size = max(13.5 * s, compact ? 8 : 10)
        return HStack(spacing: 0) {
            RoundedRectangle(cornerRadius: 2).fill(tint).frame(width: max(4 * s, 2.5))
            VStack(alignment: .leading, spacing: size * 0.1) {
                Text(title.uppercased()).font(.system(size: size * 0.85, weight: .heavy, design: .rounded))
                    .tracking(size * 0.05).foregroundStyle(Theme.muted)
                Text(value).font(.system(size: size * (compact ? 1.45 : 1.75), weight: .heavy, design: .rounded))
                    .foregroundStyle(Theme.text)
                ForEach(Array(lines.compactMap { $0 }.enumerated()), id: \.offset) { _, l in
                    Text(l).font(.system(size: size, weight: .bold, design: .rounded)).foregroundStyle(Theme.muted)
                }
            }
            .padding(.horizontal, size * 0.75)
            .padding(.vertical, size * 0.45)
        }
        .fixedSize()
        .background(Theme.surface.opacity(0.94), in: RoundedRectangle(cornerRadius: size * 0.8, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: size * 0.8, style: .continuous))
        .shadow(color: .black.opacity(0.08), radius: 6, y: 2)
        .frame(width: 1, height: 1, alignment: align)
        .position(x: x * s, y: y * s)
    }
}

/// Predbat's plan under the picture: what it's doing, the price now, today's cost and the next cheap charge.
struct EnergyPlan: View {
    let plan: EnergyOverview.Plan?
    var tariff: EnergyOverview.Tariff? = nil
    var titleSize: CGFloat = 11
    var valueSize: CGFloat = 15

    var body: some View {
        CenteredWrap(spacing: 8) {
            ForEach(Array(Energy.planItems(plan, tariff).enumerated()), id: \.offset) { _, item in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(item.0.uppercased()).font(.system(size: titleSize, weight: .heavy, design: .rounded))
                        .tracking(0.8).foregroundStyle(Theme.muted)
                    Text(item.1).font(.system(size: valueSize, weight: .heavy, design: .rounded)).foregroundStyle(Theme.text)
                }
                .padding(.horizontal, valueSize * 0.8)
                .padding(.vertical, valueSize * 0.4)
                .background(Theme.surface, in: Capsule())
            }
        }
    }
}

/// Lays its children out left to right, wrapping onto new lines, each line centred.
struct CenteredWrap: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(proposal.width ?? .infinity, subviews)
        let width = rows.map { r in r.reduce(0) { $0 + $1.width } + spacing * CGFloat(max(r.count - 1, 0)) }.max() ?? 0
        let height = rows.map { $0.map(\.height).max() ?? 0 }.reduce(0, +) + spacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY, i = 0
        for row in arrange(bounds.width, subviews) {
            let w = row.reduce(0) { $0 + $1.width } + spacing * CGFloat(max(row.count - 1, 0))
            var x = bounds.minX + (bounds.width - w) / 2
            let h = row.map(\.height).max() ?? 0
            for size in row {
                subviews[i].place(at: CGPoint(x: x, y: y + (h - size.height) / 2), proposal: ProposedViewSize(size))
                x += size.width + spacing; i += 1
            }
            y += h + spacing
        }
    }

    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> [[CGSize]] {
        var rows: [[CGSize]] = [[]], x: CGFloat = 0
        for v in subviews {
            let size = v.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { rows.append([]); x = 0 }
            rows[rows.count - 1].append(size)
            x += size.width + spacing
        }
        return rows
    }
}

/// Words and numbers shared by the picture and the phone's cards.
enum Energy {
    /// "774 W", "2.45 kW".
    static func watts(_ w: Double?) -> String {
        guard let w else { return "–" }
        let a = abs(w)
        if a < 1000 { return "\(Int(a.rounded())) W" }
        return String(format: a < 10_000 ? "%.2f kW" : "%.1f kW", a / 1000)
    }
    static func kwh(_ v: Double) -> String { String(format: v < 100 ? "%.1f kWh" : "%.0f kWh", v) }
    static func temp(_ v: Double) -> String { "\(Int(v.rounded()))°" }
    /// "19.5°", "9°".
    static func degrees(_ v: Double) -> String {
        let r = (v * 10).rounded() / 10
        return r == r.rounded() ? "\(Int(r))°" : String(format: "%.1f°", r)
    }
    static func cop(_ v: Double) -> String { String(format: "%.1f", v) }
    /// "9am", "11:30pm" from an ISO time, at the household's wall clock.
    static func time(_ iso: String) -> String { Dates(timezone: nil).time(iso) }
    static func parse(_ iso: String?) -> Date? {
        guard let iso else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: iso)
    }
    /// "34.7p", "£1.66".
    static func money(_ v: Double, _ unit: String?) -> String {
        switch unit {
        case "p", nil: return abs(v) >= 100 ? String(format: "£%.2f", v / 100) : String(format: "%gp", (v * 10).rounded() / 10)
        case "£", "GBP": return String(format: "£%.2f", v)
        default: return String(format: "%g %@", (v * 100).rounded() / 100, unit!)
        }
    }

    static func solarValue(_ s: EnergyOverview.Solar, short: Bool) -> String {
        switch solarPhase(s) {
        case .before: if let start = s.starts { return (short ? "From " : "Starts ") + time(start) }
        case .after: if !short { return "Done for today" }
        case .day: break
        }
        return watts(s.power)
    }
    static func solarLines(_ s: EnergyOverview.Solar) -> [String?] {
        switch solarPhase(s) {
        case .before:
            return [s.forecast_today.map { "\(kwh($0)) expected today" }]
        case .after:
            return [s.today.map { "\(kwh($0)) today" }, s.forecast_tomorrow.map { "Tomorrow \(kwh($0)) expected" }]
        case .day:
            guard let today = s.today else { return [] }
            if let f = s.forecast_today { return [String(format: "%.1f of %@ today", today, kwh(f))] }
            return ["\(kwh(today)) today"]
        }
    }
    static func heatPumpShort(_ hp: EnergyOverview.HeatPump) -> String? {
        if let c = hp.cop { return "COP \(cop(c))" }
        return hp.running ? shortDoing(hp.doing) : nil
    }
    static func heatPumpLines(_ hp: EnergyOverview.HeatPump) -> [String?] {
        let now: [String?] = [hp.power.map { watts($0) }, hp.cop.map { "COP \(cop($0)) now" }]
        let flow: [String?] = [hp.flow_temp.map { "Flow \(temp($0))" }, hp.today.map { "\(kwh($0)) today" }]
        let split: [String?] = [hp.cop_today?.heating.map { "Heat \(cop($0))" }, hp.cop_today?.hot_water.map { "Water \(cop($0))" }]
        return [join(now), join(flow), hp.cop_today?.overall.map { "COP today \(cop($0))" }, join(split)]
    }

    enum SolarPhase { case before, day, after }
    /// Before the panels start, producing, or done for today (from the forecast).
    static func solarPhase(_ s: EnergyOverview.Solar, now: Date = Date()) -> SolarPhase {
        if (s.power ?? 0) >= 30 { return .day }
        if let start = parse(s.starts), now < start { return .before }
        if let end = parse(s.ends), now >= end { return .after }
        if s.starts == nil, s.forecast_tomorrow != nil, Calendar.current.component(.hour, from: now) >= 15 { return .after }
        return .day
    }

    static func planItems(_ p: EnergyOverview.Plan?, _ t: EnergyOverview.Tariff?, now: Date = Date()) -> [(String, String)] {
        var out: [(String, String)] = []
        if let p { out = predbatItems(p, now: now) }
        if let t {
            func span(_ s: EnergyOverview.Tariff.Slot) -> String { time(s.start) + "–" + time(s.end) }
            var cheap: [(String, String)] = []
            if t.cheap_now { cheap.append(("Cheap rate", t.cheap_until.map { "now until " + time($0) } ?? "now")) }
            else if let n = t.next { cheap.append(("Next cheap", span(n))) }
            cheap += t.bonus.prefix(2).map { ("Bonus slot", span($0)) }
            // In place of Predbat's own cheap-rate item, before its battery charge
            out.removeAll { $0.0 == "Cheap rate" }
            let at = out.firstIndex { $0.0 == "Charging battery" } ?? out.count
            out.insert(contentsOf: cheap, at: at)
        }
        return out
    }

    private static func predbatItems(_ p: EnergyOverview.Plan, now: Date) -> [(String, String)] {
        let unit = p.rate_unit ?? "p"
        func soon(_ w: EnergyOverview.Plan.Window?) -> EnergyOverview.Plan.Window? {
            guard let w else { return nil }
            if let end = parse(w.end), end <= now { return nil }
            return w
        }
        let charge = soon(p.charge), cheap = soon(p.cheap)
        var out: [(String, String)] = []
        if let s = p.status { out.append(("Predbat", s)) }
        if let v = p.rate_now { out.append(("Price now", money(v, unit))) }
        if let v = p.rate_export { out.append(("Export", money(v, unit))) }
        if let v = p.cost_today { out.append(("Cost today", money(v, p.cost_unit ?? unit))) }
        if let h = p.battery_hours, h > 0 { out.append(("Battery lasts", h < 10 ? String(format: "%.1f h", h) : "\(Int(h.rounded())) h")) }
        if let c = charge {
            out.append(("Charging battery", time(c.start) + (c.end.map { "–" + time($0) } ?? "") + (c.rate.map { " at " + money($0, unit) } ?? "")))
        }
        if let c = cheap, c.start != charge?.start {
            let when = (parse(c.start).map { $0 <= now } ?? false) ? "now" : "from " + time(c.start)
            out.append(("Cheap rate", when + (c.rate.map { " at " + money($0, unit) } ?? "")))
        }
        return out
    }
    static func join(_ parts: [String?]) -> String? {
        let p = parts.compactMap { $0 }
        return p.isEmpty ? nil : p.joined(separator: " · ")
    }
    static func batteryLine(_ b: EnergyOverview.Battery) -> String? {
        guard let p = b.power else { return nil }
        switch b.state {
        case "idle": return "Resting"
        case "charging": return "Charging \(watts(p))"
        default: return "Powering the house \(watts(p))"
        }
    }
    static func gridValue(_ g: EnergyOverview.Grid, short: Bool) -> String {
        guard let p = g.power else { return "–" }
        switch g.state {
        case "importing": return (short ? "In " : "Buying ") + watts(p)
        case "exporting": return (short ? "Out " : "Selling ") + watts(p)
        default: return short ? "0 W" : "Nothing in or out"
        }
    }
    static func carValue(_ c: EnergyOverview.Car) -> String {
        if c.charging == true { return c.power.map { watts($0) } ?? "Charging" }
        if c.plugged_in == true { return "Plugged in" }
        if c.plugged_in == false { return "Not plugged in" }
        return c.status ?? "–"
    }
    /// "Charging to 80% by 7am".
    static func carTarget(_ c: EnergyOverview.Car) -> String? {
        switch (c.limit, c.ready) {
        case let (l?, r?): return "Charging to \(Int(l.rounded()))% by \(time(r))"
        case let (l?, nil): return "Charging to \(Int(l.rounded()))%"
        case let (nil, r?): return "Ready by \(time(r))"
        default: return nil
        }
    }
    static func shortDoing(_ doing: String) -> String? {
        switch doing {
        case "Heating the house": "Heating"
        case "Heating hot water": "Hot water"
        case "Running": nil
        default: doing
        }
    }
}

enum EnergyColors {
    static let solar = Color(hex: "#F2A33A")
    static let battery = Color(hex: "#2FB58A")
    static let grid = Color(hex: "#8B7CF0")
    static let car = Color(hex: "#4F7CEC")
    static let heat = Color(hex: "#E8674F")

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(rgb: dark) : UIColor(rgb: light) })
    }
    static let sky1 = dynamic(0xD6E8F8, 0x182033)
    static let sky2 = dynamic(0xF6F2EA, 0x1C1F29)
    static let grass = dynamic(0xCFE4BF, 0x1F2C25)
    static let wall = dynamic(0xFFFDF8, 0x2A2D38)
    static let line = dynamic(0xA99F92, 0x646A7A)
    static let roof = dynamic(0xC9775A, 0x7C4A3B)
    static let glass = dynamic(0xDBE7F3, 0x34405A)
    static let body = dynamic(0xE7E9EF, 0x3A3E4C)
    static let metal = Color(hex: "#8C909C")
    static let faint = dynamic(0xC9C3B9, 0x555967)
}

/// Draws the picture into a 1000 × 600 Canvas context. `time` drives the moving dots and the fan.
private struct EnergyScene {
    let data: EnergyOverview
    let time: TimeInterval
    var drawSun = true

    let idle = 30.0

    func draw(_ ctx: inout GraphicsContext) {
        let c = EnergyColors.self
        let solar = data.solar, battery = data.battery, grid = data.grid, car = data.car, hp = data.heat_pump
        let sunny = (solar?.power ?? 0) >= idle
        let plugged = car?.plugged_in == true || car?.charging == true

        // Sky and ground
        ctx.fill(Path(CGRect(x: 0, y: 0, width: 1000, height: 600)),
                 with: .linearGradient(Gradient(colors: [c.sky1, c.sky2]), startPoint: .zero, endPoint: CGPoint(x: 0, y: 600)))
        ctx.fill(Path(CGRect(x: 0, y: 500, width: 1000, height: 100)), with: .color(c.grass))

        // Sun (the weather's icon is drawn over the picture instead when it isn't sunny)
        if drawSun {
            let sun = sunny ? Color(hex: "#FFC24A") : c.faint
            let pulse = sunny ? 0.7 + 0.3 * sin(time * 2.1) : 1
            for i in 0..<12 {
                let a = Double(i) * .pi / 6
                var ray = Path()
                ray.move(to: CGPoint(x: 120 + sin(a) * 58, y: 96 - cos(a) * 58))
                ray.addLine(to: CGPoint(x: 120 + sin(a) * 74, y: 96 - cos(a) * 74))
                ctx.stroke(ray, with: .color(sun.opacity(pulse)), style: StrokeStyle(lineWidth: 7, lineCap: .round))
            }
            ctx.fill(Path(ellipseIn: CGRect(x: 78, y: 54, width: 84, height: 84)), with: .color(sun))
        }

        // Pylon, its cable running under the garden into the house
        if grid != nil {
            let pylon = path { p in
                p.move(to: CGPoint(x: 950, y: 500)); p.addLine(to: CGPoint(x: 975, y: 250)); p.addLine(to: CGPoint(x: 1000, y: 500))
                for (y, half) in [(430.0, 18.0), (360, 12), (300, 7)] {
                    p.move(to: CGPoint(x: 975 - half, y: y)); p.addLine(to: CGPoint(x: 975 + half, y: y))
                }
                p.move(to: CGPoint(x: 950, y: 500)); p.addLine(to: CGPoint(x: 987, y: 360))
                p.move(to: CGPoint(x: 1000, y: 500)); p.addLine(to: CGPoint(x: 963, y: 360))
                p.move(to: CGPoint(x: 957, y: 430)); p.addLine(to: CGPoint(x: 982, y: 300))
                p.move(to: CGPoint(x: 993, y: 430)); p.addLine(to: CGPoint(x: 968, y: 300))
                p.move(to: CGPoint(x: 935, y: 268)); p.addLine(to: CGPoint(x: 1015, y: 268))
                p.move(to: CGPoint(x: 942, y: 290)); p.addLine(to: CGPoint(x: 1008, y: 290))
            }
            ctx.stroke(pylon, with: .color(c.metal), style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
        }

        // House, from its long side: the roof a slope above the walls with the panels on it
        let outline = StrokeStyle(lineWidth: 4, lineJoin: .round)
        let walls = path { p in
            p.move(to: CGPoint(x: 330, y: 320)); p.addLine(to: CGPoint(x: 330, y: 500))
            p.addLine(to: CGPoint(x: 690, y: 500)); p.addLine(to: CGPoint(x: 690, y: 320))
        }
        ctx.fill(walls, with: .color(c.wall)); ctx.stroke(walls, with: .color(c.line), style: outline)
        let roof = line([(300, 322), (365, 182), (655, 182), (720, 322)], close: true)
        ctx.fill(roof, with: .color(c.roof)); ctx.stroke(roof, with: .color(c.line), style: outline)
        if solar != nil {
            for i in 0..<12 {
                let r = Path(roundedRect: CGRect(x: 384 + Double(i % 6) * 44, y: i < 6 ? 198 : 254, width: 40, height: 50), cornerRadius: 3)
                ctx.fill(r, with: .color(Color(hex: sunny ? "#31477A" : "#2C3E66")))
                ctx.stroke(r, with: .color(Color(hex: "#9FB1D6")), lineWidth: 2.5)
            }
        }

        // Hot water tank
        if let tank = data.temperatures?.tank {
            let r = Path(roundedRect: CGRect(x: 612, y: 378, width: 60, height: 104), cornerRadius: 16)
            ctx.fill(r, with: .color(Color(hex: tank >= 45 ? "#E8674F" : tank >= 35 ? "#F2A33A" : "#6AA6E8").opacity(0.9)))
            ctx.stroke(r, with: .color(c.line), lineWidth: 4)
        }

        // Flows, all through the home
        if let solar {
            flow(&ctx, line([(520, 304), (520, 429)]), solar.power, c.solar)
        }
        if let battery {
            flow(&ctx, line([(395, 440), (509, 440)]), battery.power, c.battery, back: (battery.power ?? 0) < 0)
        }
        if let grid {
            let p = path { p in
                p.move(to: CGPoint(x: 958, y: 500)); p.addQuadCurve(to: CGPoint(x: 930, y: 524), control: CGPoint(x: 956, y: 524))
                p.addLine(to: CGPoint(x: 548, y: 524)); p.addLine(to: CGPoint(x: 526, y: 451))
            }
            flow(&ctx, p, grid.power, c.grid, back: (grid.power ?? 0) < 0)
        }
        if let car {
            let w = car.charging == true ? (car.power ?? 2000) : 0
            flow(&ctx, line([(510, 448), (478, 490), (300, 490), (262, 470)]), w, c.car)
            if plugged {
                flow(&ctx, path { p in p.move(to: CGPoint(x: 262, y: 470)); p.addQuadCurve(to: CGPoint(x: 205, y: 476), control: CGPoint(x: 240, y: 500)) }, w, c.car)
            }
        }
        if let hp {
            flow(&ctx, line([(530, 449), (556, 488), (728, 488)]), hp.running ? (hp.power ?? 500) : 0, c.heat)
        }
        let hub = Path(ellipseIn: CGRect(x: 509, y: 429, width: 22, height: 22))
        ctx.fill(hub, with: .color(Theme.accent)); ctx.stroke(hub, with: .color(c.wall), lineWidth: 4)

        // Battery
        if let battery {
            let x = 350.0, y = 404.0
            ctx.fill(Path(roundedRect: CGRect(x: x + 9, y: y - 8, width: 18, height: 10), cornerRadius: 3), with: .color(c.line))
            let body = Path(roundedRect: CGRect(x: x, y: y, width: 36, height: 76), cornerRadius: 7)
            ctx.fill(body, with: .color(c.wall)); ctx.stroke(body, with: .color(c.line), lineWidth: 4)
            if let soc = battery.soc {
                let f = min(100, max(0, soc)) / 100
                ctx.fill(Path(roundedRect: CGRect(x: x + 4, y: y + 4 + 68 * (1 - f), width: 28, height: 68 * f), cornerRadius: 4),
                         with: .color(soc < 20 ? Color(hex: "#E2902B") : c.battery))
            }
            if battery.state == "charging" {
                let bolt = line([(x + 20, y + 18), (x + 12, y + 40), (x + 19, y + 40), (x + 15, y + 58), (x + 26, y + 32), (x + 19, y + 32)], close: true)
                ctx.fill(bolt, with: .color(.white))
            }
        }

        // Car and charger
        if let car {
            let charger = Path(roundedRect: CGRect(x: 250, y: 418, width: 26, height: 52), cornerRadius: 6)
            ctx.fill(charger, with: .color(c.body)); ctx.stroke(charger, with: .color(c.line), lineWidth: 3)
            ctx.stroke(line([(263, 470), (263, 500)]), with: .color(c.line), lineWidth: 4)
            let led: Color = car.charging == true ? c.car.opacity(0.6 + 0.4 * sin(time * 4.5)) : plugged ? c.battery : c.faint
            ctx.fill(Path(roundedRect: CGRect(x: 256, y: 427, width: 14, height: 10), cornerRadius: 2), with: .color(led))

            var carCtx = ctx
            carCtx.translateBy(x: 40, y: 418)
            let shell = path { p in
                p.move(to: CGPoint(x: 8, y: 68)); p.addLine(to: CGPoint(x: 8, y: 48))
                p.addQuadCurve(to: CGPoint(x: 18, y: 38), control: CGPoint(x: 8, y: 40))
                p.addLine(to: CGPoint(x: 46, y: 34)); p.addLine(to: CGPoint(x: 70, y: 12))
                p.addQuadCurve(to: CGPoint(x: 86, y: 7), control: CGPoint(x: 76, y: 7))
                p.addLine(to: CGPoint(x: 130, y: 7))
                p.addQuadCurve(to: CGPoint(x: 150, y: 16), control: CGPoint(x: 142, y: 7))
                p.addLine(to: CGPoint(x: 168, y: 36))
                p.addQuadCurve(to: CGPoint(x: 186, y: 54), control: CGPoint(x: 186, y: 40))
                p.addLine(to: CGPoint(x: 186, y: 68)); p.closeSubpath()
            }
            carCtx.fill(shell, with: .color(c.body)); carCtx.stroke(shell, with: .color(c.line), style: outline)
            carCtx.fill(line([(78, 18), (106, 18), (106, 36), (60, 36)], close: true), with: .color(c.glass))
            carCtx.fill(line([(114, 18), (134, 18), (150, 36), (114, 36)], close: true), with: .color(c.glass))
            for cx in [46.0, 148] {
                let wheel = Path(ellipseIn: CGRect(x: cx - 15, y: 55, width: 30, height: 30))
                carCtx.fill(wheel, with: .color(Color(hex: "#34373F"))); carCtx.stroke(wheel, with: .color(c.body), lineWidth: 5)
            }
            if let soc = car.soc {
                carCtx.fill(Path(roundedRect: CGRect(x: 60, y: 46, width: 72, height: 10), cornerRadius: 5), with: .color(Theme.surface2))
                carCtx.fill(Path(roundedRect: CGRect(x: 60, y: 46, width: 72 * min(100, max(0, soc)) / 100, height: 10), cornerRadius: 5), with: .color(c.car))
            }
        }

        // Heat pump
        if let hp {
            var u = ctx
            u.translateBy(x: 728, y: 430)
            let box = Path(roundedRect: CGRect(x: 0, y: 0, width: 112, height: 70), cornerRadius: 8)
            u.fill(box, with: .color(c.body)); u.stroke(box, with: .color(c.line), lineWidth: 4)
            let grille = Path(ellipseIn: CGRect(x: 16, y: 11, width: 48, height: 48))
            u.fill(grille, with: .color(c.wall)); u.stroke(grille, with: .color(c.line), lineWidth: 3)
            var fan = u
            fan.translateBy(x: 40, y: 35)
            fan.rotate(by: .radians(hp.running ? time.truncatingRemainder(dividingBy: 1.2) / 1.2 * 2 * .pi : 0))
            for i in 0..<3 {
                var blade = fan
                blade.rotate(by: .degrees(Double(i) * 120))
                blade.fill(path { p in
                    p.move(to: .zero)
                    p.addCurve(to: CGPoint(x: 0, y: -20), control1: CGPoint(x: 6, y: -10), control2: CGPoint(x: 4, y: -18))
                    p.addCurve(to: .zero, control1: CGPoint(x: -4, y: -18), control2: CGPoint(x: -6, y: -10))
                }, with: .color(c.metal))
            }
            for y in [18.0, 30, 42, 54] {
                u.stroke(line([(80, y), (100, y)]), with: .color(c.line), style: StrokeStyle(lineWidth: 3, lineCap: .round))
            }
        }
    }

    /// A wire with dots running along it, faster with more power; just the wire when nothing flows.
    private func flow(_ ctx: inout GraphicsContext, _ p: Path, _ w: Double?, _ color: Color, back: Bool = false) {
        ctx.stroke(p, with: .color(color.opacity(0.22)), style: StrokeStyle(lineWidth: 9, lineCap: .round, lineJoin: .round))
        guard let w, abs(w) >= idle else { return }
        let seconds = max(0.35, 3.2 / (1 + abs(w) / 1000))
        let progress = time.truncatingRemainder(dividingBy: seconds) / seconds
        let gap = 22.0
        let phase = back ? progress * gap : gap - progress * gap
        ctx.stroke(p, with: .color(color), style: StrokeStyle(lineWidth: 9, lineCap: .round, lineJoin: .round, dash: [0.1, gap], dashPhase: phase))
    }

    private func path(_ build: (inout Path) -> Void) -> Path {
        var p = Path()
        build(&p)
        return p
    }

    private func line(_ points: [(Double, Double)], close: Bool = false) -> Path {
        path { p in
            guard let first = points.first else { return }
            p.move(to: CGPoint(x: first.0, y: first.1))
            for pt in points.dropFirst() { p.addLine(to: CGPoint(x: pt.0, y: pt.1)) }
            if close { p.closeSubpath() }
        }
    }
}

/// The details under the picture on a narrow screen.
struct EnergyCards: View {
    let data: EnergyOverview
    var columns = 2
    var titleFont: Font = Theme.text(.caption, .heavy)
    var valueFont: Font = Theme.text(.headline, .heavy)
    var lineFont: Font = Theme.text(.subheadline, .bold)

    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12, alignment: .top), count: columns), spacing: 12) {
            ForEach(Array(cards.enumerated()), id: \.offset) { _, card in
                HStack(spacing: 0) {
                    Rectangle().fill(card.tint).frame(width: 5)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(card.title.uppercased()).font(titleFont).tracking(0.8).foregroundStyle(Theme.muted)
                        Text(card.value).font(valueFont).foregroundStyle(Theme.text)
                        ForEach(card.lines, id: \.self) { Text($0).font(lineFont).foregroundStyle(Theme.muted) }
                    }
                    .padding(12)
                    Spacer(minLength: 0)
                }
                .frame(maxHeight: .infinity, alignment: .top)
                .background(Theme.surface)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
        }
    }

    private struct Item { let tint: Color; let title: String; let value: String; let lines: [String] }

    private var cards: [Item] {
        var out: [Item] = []
        let d = data
        if let s = d.solar {
            let phase = Energy.solarPhase(s)
            out.append(Item(tint: EnergyColors.solar, title: "Solar",
                            value: phase == .before && s.starts != nil ? "Starts \(Energy.time(s.starts!))" : Energy.watts(s.power), lines: [
                s.today.map { "\(Energy.kwh($0)) today" }, s.forecast_today.map { "\(Energy.kwh($0)) expected today" },
                phase == .after ? s.forecast_tomorrow.map { "\(Energy.kwh($0)) expected tomorrow" } : nil,
            ].compactMap { $0 }))
        }
        if let b = d.battery {
            out.append(Item(tint: EnergyColors.battery, title: "Battery", value: b.soc.map { "\(Int($0.rounded()))%" } ?? "–", lines: [Energy.batteryLine(b)].compactMap { $0 }))
        }
        if let h = d.home {
            out.append(Item(tint: Theme.accent, title: "Home", value: Energy.watts(h.power), lines: [h.today.map { "\(Energy.kwh($0)) today" }].compactMap { $0 }))
        }
        if let g = d.grid {
            out.append(Item(tint: EnergyColors.grid, title: "Grid", value: Energy.gridValue(g, short: false),
                            lines: [g.import_today.map { "\(Energy.kwh($0)) bought today" }, g.export_today.map { "\(Energy.kwh($0)) sold today" }].compactMap { $0 }))
        }
        if let c = d.car {
            let value = c.charging == true ? "Charging" : c.plugged_in == true ? "Plugged in" : c.plugged_in == false ? "Not plugged in" : c.status ?? "–"
            out.append(Item(tint: EnergyColors.car, title: "Car", value: value, lines: [
                c.charging == true ? c.power.map { Energy.watts($0) } : nil,
                c.soc.map { soc in "\(Int(soc.rounded()))%" + (c.range.map { " · \(Int($0.rounded())) \(c.range_unit ?? "")" } ?? "") },
                c.session.flatMap { $0 > 0 ? "\(Energy.kwh($0)) added" : nil }, Energy.carTarget(c),
            ].compactMap { $0 }))
        }
        if let hp = d.heat_pump {
            out.append(Item(tint: EnergyColors.heat, title: "Heat pump", value: hp.running ? hp.doing : "Idle", lines: [
                hp.power.map { Energy.watts($0) }, hp.cop.map { "COP \(Energy.cop($0)) now" }, hp.flow_temp.map { "Flow \(Energy.temp($0))" },
                hp.today.map { "\(Energy.kwh($0)) today" }, hp.cop_today?.overall.map { "COP today \(Energy.cop($0))" },
                hp.cop_today?.heating.map { "Heating \(Energy.cop($0))" }, hp.cop_today?.hot_water.map { "Hot water \(Energy.cop($0))" },
            ].compactMap { $0 }))
        }
        if let t = d.temperatures, t.inside != nil || t.tank != nil {
            out.append(Item(tint: Color(hex: "#6AA6E8"), title: "Temperatures", value: t.inside.map { "\(Energy.degrees($0)) inside" } ?? "–",
                            lines: [t.tank.map { "Hot water tank \(Energy.degrees($0))" }].compactMap { $0 }))
        }
        return out
    }
}
