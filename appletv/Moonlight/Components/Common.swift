import SwiftUI

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

/// Home Assistant weather conditions as multicolour SF Symbols.
struct WeatherGlyph: View {
    let condition: String
    var size: CGFloat = 30

    var body: some View {
        Image(systemName: Self.symbol(condition))
            .symbolRenderingMode(.multicolor)
            .font(.system(size: size))
            .accessibilityLabel(condition)
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
        case "lightning-rainy": "cloud.bolt.rain.fill"
        case "snowy": "cloud.snow.fill"
        case "windy": "wind"
        default: "cloud.fill"
        }
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

/// Top row on every screen: clock, date, today's weather and the family name.
struct Header: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.everyMinute) { ctx in
            HStack(alignment: .firstTextBaseline, spacing: 28) {
                Text(model.dates.clock(ctx.date))
                    .font(Theme.font(64, .heavy))
                    .foregroundStyle(Theme.text)
                Text(model.dates.longDate(ctx.date))
                    .font(Theme.font(32, .bold))
                    .foregroundStyle(Theme.muted)
                if let w = model.weather {
                    HStack(spacing: 10) {
                        WeatherGlyph(condition: w.current.condition, size: 34)
                        Text("\(w.current.temp)°").font(Theme.font(34, .heavy)).foregroundStyle(Theme.text)
                    }
                }
                Spacer()
                Text(model.settings?.family_name ?? "")
                    .font(Theme.font(30, .heavy))
                    .foregroundStyle(Theme.muted)
            }
        }
    }
}

struct EmptyNote: View {
    let text: String
    var body: some View {
        Text(text)
            .font(Theme.font(26, .bold))
            .foregroundStyle(Theme.muted)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
            .padding(32)
    }
}

/// Shown when there's nobody in the family yet (a new install with demo data off).
struct FamilyPrompt: View {
    var text = "Add your family in Moonlight Settings › Family on your phone or wall screen, and they'll appear here."
    var body: some View {
        VStack(spacing: 20) {
            Text("👋").font(.system(size: 80))
            Text(text)
                .font(Theme.font(32, .bold))
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 1000)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// A Moonlight screen: safe-area padding, the header, then content.
struct Screen<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Header()
            content
        }
        .padding(.horizontal, Theme.gutter)
        .padding(.top, 10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.bg.ignoresSafeArea())
    }
}
