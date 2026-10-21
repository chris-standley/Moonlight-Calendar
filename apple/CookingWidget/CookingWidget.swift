import ActivityKit
import SwiftUI
import WidgetKit

@main
struct CookingWidgets: WidgetBundle {
    var body: some Widget {
        CookingActivityWidget()
        EnergyWidget()
    }
}

private let accent = Color(red: 0.42, green: 0.48, blue: 0.94)

/// The recipe being cooked: current step, and the next timer counting down (the system keeps the countdown going
/// with the app closed).
struct CookingActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CookingAttributes.self) { context in
            LockScreenCooking(attributes: context.attributes, state: context.state)
                .padding(16)
                .activitySystemActionForegroundColor(accent)
        } dynamicIsland: { context in
            let s = context.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Text(context.attributes.emoji.isEmpty ? "🍳" : context.attributes.emoji).font(.title)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if let ends = s.timerEnds {
                        Countdown(ends: ends).font(.title3.monospacedDigit().weight(.heavy)).foregroundStyle(accent)
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(context.attributes.recipe).font(.headline).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(stepLabel(s)).font(.caption.weight(.heavy)).foregroundStyle(accent)
                        Text(s.text).font(.subheadline).lineLimit(3)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } compactLeading: {
                Text(s.step > 0 ? "\(s.step)/\(s.steps)" : "✓").font(.caption.weight(.heavy)).foregroundStyle(accent)
            } compactTrailing: {
                if let ends = s.timerEnds {
                    Countdown(ends: ends).font(.caption.monospacedDigit().weight(.heavy)).frame(maxWidth: 52)
                } else {
                    Text(context.attributes.emoji.isEmpty ? "🍳" : context.attributes.emoji)
                }
            } minimal: {
                if let ends = s.timerEnds {
                    Countdown(ends: ends).font(.caption2.monospacedDigit().weight(.heavy))
                } else {
                    Text(context.attributes.emoji.isEmpty ? "🍳" : context.attributes.emoji)
                }
            }
        }
    }
}

private func stepLabel(_ s: CookingAttributes.ContentState) -> String {
    if s.ringing > 0 { return s.ringing == 1 ? "A timer has gone off" : "\(s.ringing) timers have gone off" }
    return s.step > 0 ? "Step \(s.step) of \(s.steps)" : "All done"
}

/// Counts down to `ends`, stopping at 0:00.
private struct Countdown: View {
    let ends: Date

    var body: some View {
        let start = min(Date(), ends)
        Text(timerInterval: start...ends, countsDown: true)
            .multilineTextAlignment(.trailing)
    }
}

private struct LockScreenCooking: View {
    let attributes: CookingAttributes
    let state: CookingAttributes.ContentState

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(attributes.emoji.isEmpty ? "🍳" : attributes.emoji).font(.system(size: 34))
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(attributes.recipe).font(.headline).lineLimit(1)
                    Spacer()
                    Text(stepLabel(state)).font(.caption.weight(.heavy)).foregroundStyle(accent)
                }
                Text(state.text).font(.subheadline).lineLimit(3)
                if let ends = state.timerEnds {
                    HStack(spacing: 6) {
                        Image(systemName: "timer")
                        Text(state.timerLabel ?? "Timer").lineLimit(1)
                        Spacer()
                        Countdown(ends: ends).font(.title3.monospacedDigit().weight(.heavy))
                    }
                    .foregroundStyle(accent)
                    .padding(.top, 2)
                }
            }
        }
    }
}
