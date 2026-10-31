import SwiftUI

// Small building blocks used by the TV and the iPhone/iPad apps alike.

struct Avatar: View {
    let person: Person
    var size: CGFloat = 56
    var dim = false

    var body: some View {
        Text(person.initials)
            .font(Theme.font(size * 0.4, .heavy))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(Circle().fill(Color(hex: person.color)))
            .opacity(dim ? 0.35 : 1)
            .saturation(dim ? 0.4 : 1)
            .accessibilityLabel(person.name)
    }
}

/// Overlapping avatars of everyone at an event.
struct AvatarStack: View {
    let people: [Person]
    var size: CGFloat = 34

    var body: some View {
        HStack(spacing: -size * 0.3) {
            ForEach(people) { p in
                Avatar(person: p, size: size).overlay(Circle().stroke(Theme.surface, lineWidth: 3))
            }
        }
    }
}

struct StarBadge: View {
    let value: Int
    var size: CGFloat = 26

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "star.fill").foregroundStyle(Theme.star)
            Text("\(value)")
        }
        .font(Theme.font(size, .heavy))
        .foregroundStyle(Theme.starText)
        .padding(.horizontal, size * 0.6)
        .padding(.vertical, size * 0.25)
        .background(Capsule().fill(Theme.starBg))
    }
}

/// Home Assistant weather conditions as SF Symbols, coloured so clouds and the moon show on light and dark
/// backgrounds alike (the system's multicolour versions draw them white).
struct WeatherGlyph: View {
    let condition: String
    var size: CGFloat = 30

    private static let cloud = Color(red: 0.55, green: 0.6, blue: 0.68)
    private static let sun = Color(red: 1.0, green: 0.72, blue: 0.1)

    var body: some View {
        Image(systemName: Self.symbol(condition))
            .symbolRenderingMode(.palette)
            .foregroundStyle(colors.0, colors.1, colors.2)
            .font(.system(size: size))
            .accessibilityLabel(condition)
    }

    /// Palette layers: the main shape first (cloud or moon), then what's in front of or falling from it.
    private var colors: (Color, Color, Color) {
        let rain = Color(red: 0.25, green: 0.55, blue: 0.95)
        switch condition {
        case "sunny": return (Self.sun, Self.sun, Self.sun)
        case "clear-night": return (Color(red: 0.55, green: 0.55, blue: 0.9), Self.sun, Self.sun)
        case "partlycloudy": return (Self.cloud, Self.sun, Self.sun)
        case "rainy", "pouring": return (Self.cloud, rain, rain)
        case "lightning-rainy", "lightning": return (Self.cloud, Self.sun, rain)
        case "snowy": return (Self.cloud, Color(red: 0.45, green: 0.75, blue: 0.95), rain)
        default: return (Self.cloud, Self.cloud, Self.cloud)
        }
    }

    static func symbol(_ c: String) -> String {
        switch c {
        case "sunny": "sun.max.fill"
        case "clear-night": "moon.stars.fill"
        case "partlycloudy": "cloud.sun.fill"
        case "cloudy": "cloud.fill"
        case "fog": "cloud.fog.fill"
        case "rainy": "cloud.rain.fill"
        case "pouring": "cloud.heavyrain.fill"
        case "lightning-rainy", "lightning": "cloud.bolt.rain.fill"
        case "snowy": "cloud.snow.fill"
        case "windy": "wind"
        default: "cloud.fill"
        }
    }
}

/// A day's forecast on one line: icon, high, low, and the chance of rain when there is any.
struct DayWeather: View {
    let day: Weather.Day
    var size: CGFloat = 17

    var body: some View {
        HStack(spacing: size * 0.35) {
            WeatherGlyph(condition: day.condition, size: size * 1.2)
            Text("\(day.high)°").font(Theme.font(size, .heavy)).foregroundStyle(Theme.text)
            Text("\(day.low)°").font(Theme.font(size, .bold)).foregroundStyle(Theme.muted)
            if let rain = day.rain, rain > 0 {
                Label("\(rain)%", systemImage: "drop.fill")
                    .labelStyle(.titleAndIcon)
                    .font(Theme.font(size * 0.8, .heavy))
                    .foregroundStyle(Color(hex: "#2F74C8"))
                    .padding(.horizontal, size * 0.45).padding(.vertical, size * 0.12)
                    .background(Color(hex: "#2F74C8").opacity(0.12), in: Capsule())
                    .accessibilityLabel("\(rain)% chance of rain")
            }
        }
        .lineLimit(1)
        .fixedSize()
    }
}

/// Progress ring around an avatar, as on the chore chart.
struct ProgressRing: View {
    let person: Person
    let done: Int
    let total: Int
    var size: CGFloat = 76

    var body: some View {
        let color = Color(hex: person.color)
        ZStack {
            Circle().stroke(color.opacity(0.18), lineWidth: size * 0.07)
            Circle()
                .trim(from: 0, to: total == 0 ? 0 : CGFloat(done) / CGFloat(total))
                .stroke(color, style: StrokeStyle(lineWidth: size * 0.07, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.spring(duration: 0.5), value: done)
            Avatar(person: person, size: size * 0.74)
        }
        .frame(width: size, height: size)
    }
}


/// Colours for an event, as the wall screens draw them: tinted card, person-coloured stripe (split for several people).
struct EventColors {
    let main: Color
    let stripe: [Color]
    let busy: Bool

    init(_ o: Occurrence, people: [Person]) {
        let colors = o.person_ids.compactMap { id in people.first { $0.id == id }?.color }
        let hex = (o.busy != nil ? o.color : nil) ?? colors.first ?? o.color ?? Theme.fallbackEvent
        main = Color(hex: hex)
        busy = o.busy != nil
        stripe = colors.count > 1 && !busy ? colors.map(Color.init(hex:)) : [main]
    }
}

extension Occurrence {
    /// Free/busy blocks read "Alex – busy" (the feed's own "Busy" says nothing).
    func displayTitle(_ people: [Person]) -> String {
        guard let busy else { return title }
        let names = person_ids.compactMap { id in people.first { $0.id == id }?.name }
        let label = ["busy": "busy", "tentative": "tentative", "away": "away", "elsewhere": "working elsewhere"][busy] ?? busy
        return names.isEmpty ? label.capitalized : "\(names.joined(separator: " & ")) – \(label)"
    }
}

/// The crescent mark from the wall screens' rail.
struct LogoMark: View {
    var size: CGFloat = 80

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.28, style: .continuous).fill(Theme.logoGradient)
            Canvas { ctx, sz in
                let s = sz.width / 32
                // Crescent: a disc with an offset disc cut out (path from the web logo, M19.5 7.5a9 9 0 100 17 7.2 7.2 0 010-17z).
                var moon = Path(ellipseIn: CGRect(x: 6.5 * s, y: 7.5 * s, width: 17 * s, height: 17 * s))
                moon = moon.subtracting(Path(ellipseIn: CGRect(x: 12.3 * s, y: 7.5 * s, width: 14.4 * s, height: 17 * s)))
                ctx.fill(moon, with: .color(.white))
                ctx.fill(Path(ellipseIn: CGRect(x: 21.7 * s, y: 8.7 * s, width: 2.6 * s, height: 2.6 * s)), with: .color(.white.opacity(0.85)))
                ctx.fill(Path(ellipseIn: CGRect(x: 24.6 * s, y: 14.1 * s, width: 1.8 * s, height: 1.8 * s)), with: .color(.white.opacity(0.7)))
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// One countdown as a pill: emoji, the days to go in big numbers, and what it's to. `scale` 1 = phone size.
struct CountdownPill: View {
    let countdown: Countdown
    var scale: CGFloat = 1

    var body: some View {
        let c = countdown
        let soon = c.days <= 1
        HStack(spacing: 8 * scale) {
            Text(c.symbol).font(.system(size: 24 * scale))
            if !soon {
                Text("\(c.days)").font(Theme.font(26 * scale, .black)).foregroundStyle(Theme.accent).monospacedDigit()
            }
            VStack(alignment: .leading, spacing: 0) {
                Text(soon ? (c.days <= 0 ? "TODAY!" : "TOMORROW") : "DAYS TO")
                    .font(Theme.font(10 * scale, .heavy)).kerning(0.5)
                    .foregroundStyle(soon ? Theme.accent : Theme.muted)
                Text(c.title).font(Theme.font(15 * scale, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
            }
        }
        .padding(.leading, 10 * scale).padding(.trailing, 14 * scale).padding(.vertical, 6 * scale)
        .background(soon ? Theme.accent.opacity(0.12) : Theme.surface, in: Capsule())
        .overlay(Capsule().strokeBorder(soon ? Theme.accent : Theme.surface2, lineWidth: 1.5))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(c.sentence)
    }
}
