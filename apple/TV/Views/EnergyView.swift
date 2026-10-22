import SwiftUI

/// Energy on the TV: the house picture with solar, battery, grid, car and heat pump, live from Home Assistant.
struct EnergyView: View {
    @Environment(AppModel.self) private var model
    @State private var data: EnergyOverview?

    var body: some View {
        Screen(weather: false) {
            if data?.reachable == false {
                Text("Can't reach Home Assistant").font(Theme.font(26, .bold)).foregroundStyle(Theme.danger)
            }
            if let data, !data.isEmpty {
                // The picture as tall as the screen allows; the plan goes in a column beside it, in the width left over.
                HStack(spacing: 24) {
                    EnergyHouse(data: data, sky: model.weather?.current)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    let items = Energy.planItems(data.plan, data.tariff)
                    if !items.isEmpty {
                        VStack(alignment: .leading, spacing: 14) {
                            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.0.uppercased()).font(Theme.font(18, .heavy)).tracking(0.8).foregroundStyle(Theme.muted)
                                    Text(item.1).font(Theme.font(28, .heavy)).foregroundStyle(Theme.text)
                                        .lineLimit(2).minimumScaleFactor(0.7)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 22)
                                .padding(.vertical, 14)
                                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                            }
                        }
                        .frame(width: 320)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if data != nil {
                FamilyPrompt(text: "Pick your solar, battery, car and heat pump sensors in Moonlight Settings › Energy on a wall screen.")
            }
        }
        // Readings change every few seconds while power flows; Moonlight says when.
        .task(id: model.rev("energy", "settings")) {
            if let d = await model.call({ try await $0.energy() }) { data = d }
        }
    }
}
