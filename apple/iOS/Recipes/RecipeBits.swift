import SwiftUI

/// 0–5 stars; tappable when `onChange` is given (tap the current rating again to clear it).
struct Stars: View {
    let value: Int
    var size: CGFloat = 16
    var onChange: ((Int) -> Void)? = nil

    var body: some View {
        HStack(spacing: size * 0.2) {
            ForEach(1...5, id: \.self) { n in
                let star = Image(systemName: n <= value ? "star.fill" : "star")
                    .font(.system(size: size, weight: .semibold))
                    .foregroundStyle(n <= value ? Theme.star : Theme.muted.opacity(0.6))
                if let onChange {
                    Button { onChange(n == value ? 0 : n) } label: { star.padding(2) }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(n) star\(n == 1 ? "" : "s")")
                } else {
                    star
                }
            }
        }
        .accessibilityElement(children: onChange == nil ? .ignore : .contain)
        .accessibilityLabel(onChange == nil ? "\(value) of 5 stars" : "Rating")
    }
}

/// The recipe's picture, or its emoji on a soft colour when it has none.
struct RecipeArt: View {
    let recipe: Recipe
    var emojiSize: CGFloat = 44

    private static let tints: [Color] = [Color(hex: "#DDE3FB"), Color(hex: "#E2EEDF"), Color(hex: "#EEDDF4"),
                                         Color(hex: "#FFE0D9"), Color(hex: "#FFE9C7")]

    var body: some View {
        ZStack {
            let tint = Self.tints[abs(recipe.title.unicodeScalars.reduce(0) { $0 &+ Int($1.value) }) % Self.tints.count]
            tint.opacity(0.9)
            Text(recipe.emoji.isEmpty ? "🍽️" : recipe.emoji).font(.system(size: emojiSize))
            if recipe.photo_url != nil {
                RemoteImage(path: recipe.photo_url)
            }
        }
        .clipped()
    }
}

/// − 4 servings +  (or "1½× recipe" when the recipe doesn't say how many it serves).
struct ServingsStepper: View {
    let recipe: Recipe
    @Binding var servings: Double

    var body: some View {
        let step: Double = recipe.servings == nil ? 0.5 : 1
        let top: Double = recipe.servings == nil ? 10 : 100
        HStack(spacing: 4) {
            Button { servings = max(step, servings - step) } label: { Image(systemName: "minus").frame(width: 34, height: 34) }
                .disabled(servings <= step)
                .accessibilityLabel("Fewer")
            Text(RecipeText.servings(recipe, servings))
                .font(Theme.text(.subheadline, .heavy))
                .monospacedDigit()
                .frame(minWidth: 96)
            Button { servings = min(top, servings + step) } label: { Image(systemName: "plus").frame(width: 34, height: 34) }
                .accessibilityLabel("More")
        }
        .buttonStyle(.plain)
        .foregroundStyle(Theme.text)
        .background(Theme.surface2, in: Capsule())
    }
}

/// One ingredient: the line (scaled), with its metric amount after it when the recipe uses cups, ounces and the like.
struct IngredientLine: View {
    let ing: Ingredient
    let factor: Double

    var body: some View {
        if ing.heading {
            Text(ing.name.uppercased())
                .font(Theme.text(.caption, .heavy))
                .foregroundStyle(Theme.muted)
                .padding(.top, 6)
        } else {
            (Text(RecipeText.line(ing, factor)).foregroundStyle(Theme.text)
             + Text(RecipeText.metric(ing, factor).map { "  \($0)" } ?? "").foregroundStyle(Theme.accent))
                .font(Theme.text(.body, .semibold))
        }
    }
}

/// Prep / cook / total.
struct TimeFacts: View {
    let recipe: Recipe

    private struct Fact { let label: String; let minutes: Int? }

    var body: some View {
        let facts = [Fact(label: "Prep", minutes: recipe.prep_minutes), Fact(label: "Cook", minutes: recipe.cook_minutes),
                     Fact(label: "Total", minutes: recipe.minutes)].filter { $0.minutes != nil }
        HStack(spacing: 22) {
            ForEach(facts, id: \.label) { f in
                VStack(alignment: .leading, spacing: 1) {
                    Text(f.label.uppercased()).font(Theme.text(.caption2, .heavy)).foregroundStyle(Theme.muted)
                    Text(RecipeText.minutes(f.minutes)).font(Theme.text(.headline, .heavy)).foregroundStyle(Theme.text)
                }
            }
        }
    }
}

/// The amounts of the ingredients a step mentions ("225 g butter · 2 eggs"), scaled, with metric where it helps.
struct StepAmounts: View {
    let recipe: Recipe
    let step: RecipeStep
    let factor: Double
    var big = false

    var body: some View {
        let ings = (step.uses ?? []).filter { recipe.ingredients.indices.contains($0) }.map { recipe.ingredients[$0] }
        if !ings.isEmpty {
            FlowRow(spacing: 6) {
                ForEach(ings.indices, id: \.self) { n in
                    let ing = ings[n]
                    (Text(RecipeText.line(ing, factor, withNote: false)).foregroundStyle(Theme.text)
                     + Text(RecipeText.metric(ing, factor).map { " (\($0))" } ?? "").foregroundStyle(Theme.accent))
                        .font(Theme.text(big ? .headline : .footnote, .bold))
                        .padding(.horizontal, big ? 14 : 10).padding(.vertical, big ? 7 : 4)
                        .background(Theme.surface2, in: Capsule())
                }
            }
        }
    }
}

/// Lays its children out in rows, wrapping onto a new row when one is full.
struct FlowRow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews)
        let width = rows.map { $0.width }.max() ?? 0
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(0, rows.count - 1))
        return CGSize(width: proposal.width.map { min($0, width) } ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews) {
            var x = bounds.minX
            for i in row.items {
                let size = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row { var items: [Int] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(width: CGFloat, _ subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var row = Row()
        for i in subviews.indices {
            let size = subviews[i].sizeThatFits(.unspecified)
            let extra = row.items.isEmpty ? size.width : row.width + spacing + size.width
            if extra > width && !row.items.isEmpty {
                rows.append(row)
                row = Row()
            }
            row.width = row.items.isEmpty ? size.width : row.width + spacing + size.width
            row.height = max(row.height, size.height)
            row.items.append(i)
        }
        if !row.items.isEmpty { rows.append(row) }
        return rows
    }
}
