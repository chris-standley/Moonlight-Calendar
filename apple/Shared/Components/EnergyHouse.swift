import SwiftUI
import UIKit

/// The Energy picture (as on the wall screens): a house with solar on the roof, the battery inside, the grid, the car
/// and the heat pump around it, with dots running along the lines as power flows. Drawn in a 1000 × 600 space and
/// scaled to fit. `compact` keeps only the headline numbers on the picture (a phone shows the rest in cards below).
struct EnergyHouse: View {
    let data: EnergyOverview
    var compact = false

    var body: some View {
        GeometryReader { geo in
            let s = geo.size.width / 1000
            ZStack(alignment: .topLeading) {
                TimelineView(.animation) { tl in
                    Canvas { ctx, _ in
                        ctx.scaleBy(x: s, y: s)
                        EnergyScene(data: data, time: tl.date.timeIntervalSinceReferenceDate).draw(&ctx)
                    }
                }
                chips(s)
            }
        }
        .aspectRatio(10 / 6, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func chips(_ s: CGFloat) -> some View {
        let d = data
        if let solar = d.solar {
            chip(s, 185, 96, .leading, EnergyColors.solar, "Solar", Energy.watts(solar.power),
                 [compact ? nil : solar.today.map { "\(Energy.kwh($0)) today" }])
        }
        if let b = d.battery {
            chip(s, compact ? 370 : 380, compact ? 300 : 340, .center, EnergyColors.battery, "Battery",
                 b.soc.map { "\(Int($0.rounded()))%" } ?? "–", [compact ? nil : Energy.batteryLine(b)])
        }
        if let h = d.home {
            chip(s, compact ? 515 : 545, compact ? 245 : 268, .center, Theme.accent, compact ? "Home" : "Home is using",
                 Energy.watts(h.power), [compact ? nil : h.today.map { "\(Energy.kwh($0)) today" }])
        }
        if let g = d.grid {
            chip(s, compact ? 990 : 980, 150, .trailing, EnergyColors.grid, "Grid", Energy.gridValue(g, short: compact),
                 compact ? [] : [g.import_today.map { "\(Energy.kwh($0)) bought today" }, g.export_today.map { "\(Energy.kwh($0)) sold today" }])
        }
        if let c = d.car {
            chip(s, compact ? 120 : 135, compact ? 300 : 330, .center, EnergyColors.car, "Car", Energy.carValue(c),
                 [c.soc.map { soc in "\(Int(soc.rounded()))%" + (!compact ? c.range.map { " · \(Int($0.rounded())) \(c.range_unit ?? "")" } ?? "" : "") },
                  compact ? nil : (c.charging == true ? "Charging" : nil),
                  compact ? nil : c.session.flatMap { $0 > 0 ? "\(Energy.kwh($0)) added" : nil }])
        }
        if let hp = d.heat_pump {
            chip(s, 790, compact ? 375 : 372, .center, EnergyColors.heat, "Heat pump",
                 compact ? (hp.running ? Energy.watts(hp.power) : "Idle") : (hp.running ? hp.doing : "Idle"),
                 compact ? [hp.running ? Energy.shortDoing(hp.doing) : nil]
                         : [hp.power.map { Energy.watts($0) }, Energy.join([hp.flow_temp.map { "Flow \(Energy.temp($0))" }, hp.tank_temp.map { "Tank \(Energy.temp($0))" }]),
                            Energy.join([hp.outdoor_temp.map { "Outside \(Energy.temp($0))" }, hp.today.map { "\(Energy.kwh($0)) today" }])])
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
    static let lit = dynamic(0xFFE3A1, 0xB08A3C)
    static let door = dynamic(0x8A6A52, 0x5C4636)
    static let body = dynamic(0xE7E9EF, 0x3A3E4C)
    static let metal = Color(hex: "#8C909C")
    static let faint = dynamic(0xC9C3B9, 0x555967)
}

/// Draws the picture into a 1000 × 600 Canvas context. `time` drives the moving dots and the fan.
private struct EnergyScene {
    let data: EnergyOverview
    let time: TimeInterval

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

        // Sun
        if solar != nil {
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

        // Pylon and its wire
        let gridWire = path { p in
            p.move(to: CGPoint(x: 882, y: 290)); p.addQuadCurve(to: CGPoint(x: 690, y: 312), control: CGPoint(x: 790, y: 305))
        }
        if grid != nil {
            let pylon = path { p in
                p.move(to: CGPoint(x: 890, y: 500)); p.addLine(to: CGPoint(x: 915, y: 250)); p.addLine(to: CGPoint(x: 940, y: 500))
                for (y, half) in [(430.0, 18.0), (360, 12), (300, 7)] {
                    p.move(to: CGPoint(x: 915 - half, y: y)); p.addLine(to: CGPoint(x: 915 + half, y: y))
                }
                p.move(to: CGPoint(x: 890, y: 500)); p.addLine(to: CGPoint(x: 927, y: 360))
                p.move(to: CGPoint(x: 940, y: 500)); p.addLine(to: CGPoint(x: 903, y: 360))
                p.move(to: CGPoint(x: 897, y: 430)); p.addLine(to: CGPoint(x: 922, y: 300))
                p.move(to: CGPoint(x: 933, y: 430)); p.addLine(to: CGPoint(x: 908, y: 300))
                p.move(to: CGPoint(x: 875, y: 268)); p.addLine(to: CGPoint(x: 955, y: 268))
                p.move(to: CGPoint(x: 882, y: 290)); p.addLine(to: CGPoint(x: 948, y: 290))
            }
            ctx.stroke(pylon, with: .color(c.metal), style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
            ctx.stroke(gridWire, with: .color(c.metal), lineWidth: 2.5)
        }

        // House
        let outline = StrokeStyle(lineWidth: 4, lineJoin: .round)
        let walls = path { p in
            p.move(to: CGPoint(x: 330, y: 305)); p.addLine(to: CGPoint(x: 330, y: 500))
            p.addLine(to: CGPoint(x: 690, y: 500)); p.addLine(to: CGPoint(x: 690, y: 305))
        }
        ctx.fill(walls, with: .color(c.wall)); ctx.stroke(walls, with: .color(c.line), style: outline)
        let roof = path { p in
            p.move(to: CGPoint(x: 300, y: 312)); p.addLine(to: CGPoint(x: 510, y: 150)); p.addLine(to: CGPoint(x: 720, y: 312))
        }
        ctx.fill(roof, with: .color(c.roof)); ctx.stroke(roof, with: .color(c.line), style: outline)
        let chimney = Path(CGRect(x: 585, y: 178, width: 34, height: 62))
        ctx.fill(chimney, with: .color(c.wall)); ctx.stroke(chimney, with: .color(c.line), style: outline)
        ctx.fill(Path(roundedRect: CGRect(x: 560, y: 410, width: 58, height: 90), cornerRadius: 6), with: .color(c.door))
        let window = Path(roundedRect: CGRect(x: 610, y: 335, width: 52, height: 45), cornerRadius: 6)
        ctx.fill(window, with: .color((data.home?.power ?? 0) > 0 ? c.lit : c.glass))
        ctx.stroke(window, with: .color(c.line), lineWidth: 3)

        // Solar panels along the roof
        if solar != nil {
            var panels = ctx
            panels.translateBy(x: 338, y: 284)
            panels.rotate(by: .degrees(-37.6))
            let r = Path(roundedRect: CGRect(x: 0, y: -34, width: 170, height: 30), cornerRadius: 3)
            panels.fill(r, with: .color(Color(hex: "#2C3E66")))
            panels.stroke(r, with: .color(Color(hex: "#9FB1D6")), lineWidth: 2.5)
            let cells = path { p in
                for x in [42.0, 85, 128] { p.move(to: CGPoint(x: x, y: -34)); p.addLine(to: CGPoint(x: x, y: -4)) }
                p.move(to: CGPoint(x: 0, y: -19)); p.addLine(to: CGPoint(x: 170, y: -19))
            }
            panels.stroke(cells, with: .color(Color(hex: "#7F93BD")), lineWidth: 2)
        }

        // Flows, all through the home
        if let solar {
            flow(&ctx, line([(420, 230), (475, 330), (500, 420)]), solar.power, c.solar)
        }
        if let battery {
            flow(&ctx, line([(395, 440), (520, 440)]), battery.power, c.battery, back: (battery.power ?? 0) < 0)
        }
        if let grid {
            var p = gridWire
            p.addLine(to: CGPoint(x: 620, y: 380)); p.addLine(to: CGPoint(x: 560, y: 440))
            flow(&ctx, p, grid.power, c.grid, back: (grid.power ?? 0) < 0)
        }
        if let car {
            let w = car.charging == true ? (car.power ?? 2000) : 0
            flow(&ctx, line([(500, 455), (330, 470), (262, 470)]), w, c.car)
            if plugged {
                flow(&ctx, path { p in p.move(to: CGPoint(x: 262, y: 470)); p.addQuadCurve(to: CGPoint(x: 205, y: 476), control: CGPoint(x: 240, y: 500)) }, w, c.car)
            }
        }
        if let hp {
            flow(&ctx, line([(560, 470), (690, 470), (728, 470)]), hp.running ? (hp.power ?? 500) : 0, c.heat)
        }
        let hub = Path(ellipseIn: CGRect(x: 519, y: 429, width: 22, height: 22))
        ctx.fill(hub, with: .color(Theme.accent)); ctx.stroke(hub, with: .color(c.wall), lineWidth: 4)

        // Battery
        if let battery {
            let x = 350.0, y = 395.0
            ctx.fill(Path(roundedRect: CGRect(x: x + 9, y: y - 8, width: 18, height: 10), cornerRadius: 3), with: .color(c.line))
            let body = Path(roundedRect: CGRect(x: x, y: y, width: 36, height: 96), cornerRadius: 7)
            ctx.fill(body, with: .color(c.wall)); ctx.stroke(body, with: .color(c.line), lineWidth: 4)
            if let soc = battery.soc {
                let f = min(100, max(0, soc)) / 100
                ctx.fill(Path(roundedRect: CGRect(x: x + 4, y: y + 4 + 88 * (1 - f), width: 28, height: 88 * f), cornerRadius: 4),
                         with: .color(soc < 20 ? Color(hex: "#E2902B") : c.battery))
            }
            if battery.state == "charging" {
                let bolt = line([(x + 20, y + 30), (x + 12, y + 52), (x + 19, y + 52), (x + 15, y + 70), (x + 26, y + 44), (x + 19, y + 44)], close: true)
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
            out.append(Item(tint: EnergyColors.solar, title: "Solar", value: Energy.watts(s.power), lines: [s.today.map { "\(Energy.kwh($0)) today" }].compactMap { $0 }))
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
                c.session.flatMap { $0 > 0 ? "\(Energy.kwh($0)) added" : nil },
            ].compactMap { $0 }))
        }
        if let hp = d.heat_pump {
            out.append(Item(tint: EnergyColors.heat, title: "Heat pump", value: hp.running ? hp.doing : "Idle", lines: [
                hp.power.map { Energy.watts($0) }, hp.flow_temp.map { "Flow \(Energy.temp($0))" }, hp.tank_temp.map { "Hot water tank \(Energy.temp($0))" },
                hp.outdoor_temp.map { "Outside \(Energy.temp($0))" }, hp.today.map { "\(Energy.kwh($0)) today" },
            ].compactMap { $0 }))
        }
        return out
    }
}
