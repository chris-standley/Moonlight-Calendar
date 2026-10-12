import SwiftUI

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
extension View {
    /// For a scroll view inside a panel: clip the top and bottom (so rows don't run past the panel), but let a focused
    /// card's lift and shadow spill out at the sides instead of being cut off.
    func clipTopAndBottom(spill: CGFloat = 80) -> some View {
        scrollClipDisabled().mask(Rectangle().padding(.horizontal, -spill))
    }
}

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
