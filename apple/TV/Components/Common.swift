import SwiftUI

/// The clock in the top-left corner, beside the tab bar: the time, with the date and today's weather on one small
/// line under it, so the screen below gets all the height.
struct Header: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.everyMinute) { ctx in
            VStack(alignment: .leading, spacing: 0) {
                Text(model.dates.clock(ctx.date))
                    .font(Theme.font(44, .heavy))
                    .foregroundStyle(Theme.text)
                HStack(spacing: 8) {
                    Text(model.dates.shortDate(ctx.date))
                    if let w = model.weather {
                        WeatherGlyph(condition: w.current.condition, size: 20)
                        Text("\(w.current.temp)°").foregroundStyle(Theme.text)
                    }
                }
                .font(Theme.font(20, .bold))
                .foregroundStyle(Theme.muted)
            }
            .lineLimit(1)
            .fixedSize()
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

extension View {
    /// For a scroll view inside a panel: clip the top and bottom (so rows don't run past the panel), but let a focused
    /// card's lift and shadow spill out at the sides instead of being cut off.
    func clipTopAndBottom(spill: CGFloat = 80) -> some View {
        scrollClipDisabled().mask(Rectangle().padding(.horizontal, -spill))
    }
}

/// A Moonlight screen: safe-area padding and the content, with the clock up beside the tab bar.
struct Screen<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(.horizontal, Theme.gutter)
            .padding(.top, 10)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            // Up in the corner level with the tab bar, which floats in the middle of the top edge.
            .overlay(alignment: .topLeading) {
                Header()
                    .padding(.leading, Theme.gutter)
                    .padding(.top, 40)
                    .ignoresSafeArea(edges: .top)
            }
            .background(Theme.bg.ignoresSafeArea())
    }
}
