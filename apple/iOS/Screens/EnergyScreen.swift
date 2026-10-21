import SwiftUI

/// Energy: the house picture with solar, battery, grid, car and heat pump from Home Assistant (as on the wall
/// screens). On a narrow screen the picture keeps the headline numbers and the details go in cards below.
struct EnergyScreen: View {
    @Environment(AppModel.self) private var model
    @State private var data: EnergyOverview?

    var body: some View {
        Page(title: "Energy") { room in
            ScrollView {
                VStack(spacing: 16) {
                    if let data {
                        if !data.configured {
                            EmptyHint(text: "Energy shows your solar, battery, car and heat pump from Home Assistant. It needs Moonlight running as the Home Assistant add-on.")
                        } else if data.isEmpty {
                            EmptyHint(text: "Nothing to show yet. Pick your sensors in Moonlight Settings › Energy on a wall screen.")
                        } else {
                            if !data.reachable {
                                Text("Can't reach Home Assistant").font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.danger)
                            }
                            EnergyHouse(data: data, compact: room == .narrow)
                                .shadow(color: .black.opacity(0.05), radius: 8, y: 3)
                            if room == .narrow { EnergyCards(data: data) }
                        }
                    } else {
                        ProgressView().padding(40)
                    }
                }
                .padding(16)
                .frame(maxWidth: 1400)
                .frame(maxWidth: .infinity)
            }
        } tools: {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("Refresh")
            }
        }
        // Moonlight says when the readings change (every few seconds at most while power is flowing).
        .task(id: model.rev("energy", "settings")) { await load() }
    }

    private func load() async {
        if let d = await model.call({ try await $0.energy() }) { data = d }
    }
}
