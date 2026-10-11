import SwiftUI

/// The week's meal plan: a row per meal, a column per day.
struct MealsView: View {
    @Environment(AppModel.self) private var model
    @State private var anchor: String?
    @State private var meals: [Meal] = []

    var body: some View {
        let d = model.dates
        let start = d.weekStart(anchor ?? d.today, start: model.settings?.week_start ?? "monday")
        let days = d.days(from: start, count: 7)
        let slots = MealSlot.allCases.filter { s in s != .snack || meals.contains { $0.slot == s.rawValue } }
        Screen {
            HStack(spacing: 18) {
                Button("This week") { anchor = nil }.buttonStyle(.pill)
                Button { anchor = d.addDays(start, -7) } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(.pill).accessibilityLabel("Previous week")
                Button { anchor = d.addDays(start, 7) } label: { Image(systemName: "chevron.right") }
                    .buttonStyle(.pill).accessibilityLabel("Next week")
                Text("Meals · \(d.dayMonth(days.first!)) – \(d.dayMonth(days.last!))")
                    .font(Theme.font(40, .heavy)).foregroundStyle(Theme.text).padding(.leading, 10)
                Spacer()
            }
            Grid(horizontalSpacing: 14, verticalSpacing: 14) {
                GridRow {
                    Color.clear.frame(width: 170, height: 1)
                    ForEach(days, id: \.self) { day in
                        VStack(spacing: 2) {
                            Text(d.dow(day)).font(Theme.font(20, .heavy)).foregroundStyle(day == d.today ? Theme.accent : Theme.muted)
                            Text(d.dayNum(day)).font(Theme.font(34, .heavy)).foregroundStyle(day == d.today ? Theme.accent : Theme.text)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                ForEach(slots) { slot in
                    GridRow {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(slot.emoji).font(.system(size: 40))
                            Text(slot.label).font(Theme.font(24, .heavy)).foregroundStyle(Theme.text)
                        }
                        .frame(width: 170, alignment: .leading)
                        ForEach(days, id: \.self) { day in
                            let meal = meals.first { $0.date == day && $0.slot == slot.rawValue }
                            VStack(alignment: .leading, spacing: 6) {
                                Text(meal?.title ?? "—")
                                    .font(Theme.font(24, .heavy))
                                    .foregroundStyle(meal == nil ? Theme.muted : Theme.text)
                                    .lineLimit(3)
                                if let notes = meal?.notes, !notes.isEmpty {
                                    Text(notes).font(Theme.font(18, .semibold)).foregroundStyle(Theme.muted).lineLimit(2)
                                }
                            }
                            .padding(16)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                            .background(slot == .dinner && meal != nil ? Theme.mealBg : Theme.surface,
                                        in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                            .overlay {
                                if day == d.today {
                                    RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.accent.opacity(0.6), lineWidth: 2)
                                }
                            }
                        }
                    }
                    .frame(maxHeight: .infinity)
                }
            }
            .padding(.bottom, 50)
        }
        .task(id: "\(start)|\(model.rev("meals"))") {
            if let v = await model.call({ try await $0.meals(start, d.addDays(start, 7)) }) { meals = v }
        }
    }
}
