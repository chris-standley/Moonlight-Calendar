import SwiftUI

/// Energy on the TV: the house picture with solar, battery, grid, car and heat pump, live from Home Assistant.
struct EnergyView: View {
    @Environment(AppModel.self) private var model
    @State private var data: EnergyOverview?

    var body: some View {
        Screen {
            HStack(alignment: .firstTextBaseline, spacing: 20) {
                Text("Energy").font(Theme.font(40, .heavy)).foregroundStyle(Theme.text)
                if data?.reachable == false {
                    Text("Can't reach Home Assistant").font(Theme.font(26, .bold)).foregroundStyle(Theme.danger)
                }
            }
            if let data, !data.isEmpty {
                EnergyHouse(data: data, sky: model.weather?.current)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                if data.plan != nil || data.tariff != nil {
                    EnergyPlan(plan: data.plan, tariff: data.tariff, titleSize: 18, valueSize: 26)
                        .frame(maxWidth: .infinity)
                }
                Spacer().frame(height: 30)
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
