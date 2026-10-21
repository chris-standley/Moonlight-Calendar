import SwiftUI
import WidgetKit

/// The Energy picture on the Home Screen: the same house as the app's Energy tab, with the headline numbers. It reads
/// the app's pairing from the shared Keychain and asks Moonlight itself, so it needs no app group.
struct EnergyWidget: Widget {
    static let kind = "MoonlightEnergy"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: Self.kind, provider: EnergyProvider()) { entry in
            EnergyWidgetView(entry: entry)
        }
        .configurationDisplayName("Energy")
        .description("Solar, battery, grid, car and heat pump, drawn as your house.")
        .supportedFamilies([.systemMedium, .systemLarge, .systemExtraLarge])
        .contentMarginsDisabled()
    }
}

struct EnergyEntry: TimelineEntry {
    var date = Date()
    var data: EnergyOverview?
    var sky: Weather.Current?
    /// Why there's no picture: not paired, not set up, or Moonlight didn't answer.
    var problem: String?
}

struct EnergyProvider: TimelineProvider {
    /// How often the widget asks for fresh readings (the app also redraws it when opened).
    private let every: TimeInterval = 15 * 60

    func placeholder(in context: Context) -> EnergyEntry { EnergyEntry(data: .sample) }

    func getSnapshot(in context: Context, completion: @escaping (EnergyEntry) -> Void) {
        if context.isPreview { return completion(EnergyEntry(data: .sample)) }
        Task { completion(await Self.load()) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<EnergyEntry>) -> Void) {
        Task {
            let entry = await Self.load()
            let refresh = Date().addingTimeInterval(every)
            var entries = [entry]
            // Sunset or sunrise before the next refresh: switch the picture over then.
            if var data = entry.data, let sun = data.sun, let at = Energy.parse(sun.next), at > entry.date, at < refresh {
                data.sun?.night.toggle()
                entries.append(EnergyEntry(date: at, data: data, sky: entry.sky))
            }
            completion(Timeline(entries: entries, policy: .after(refresh)))
        }
    }

    static func load() async -> EnergyEntry {
        guard let token = Credentials.token, let server = await Credentials.reachableServer() else {
            return EnergyEntry(problem: "Open Moonlight on this iPhone and pair it to see your energy here.")
        }
        let api = APIClient(baseURL: server, token: token)
        async let weather = try? api.weather()
        do {
            let data = try await api.energy()
            if !data.configured { return EnergyEntry(problem: "Energy needs Moonlight running as the Home Assistant add-on.") }
            if data.isEmpty { return EnergyEntry(problem: "Pick your sensors in Moonlight Settings › Energy on a wall screen.") }
            return EnergyEntry(data: data, sky: await weather?.current)
        } catch {
            return EnergyEntry(problem: "Can't reach Moonlight right now.")
        }
    }
}

struct EnergyWidgetView: View {
    let entry: EnergyEntry
    @Environment(\.widgetFamily) private var family
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Group {
            if let data = entry.data {
                if family == .systemMedium { medium(data) } else { large(data) }
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "bolt.house.fill").font(.title).foregroundStyle(EnergyColors.solar)
                    Text(entry.problem ?? "").font(Theme.text(.subheadline, .bold)).foregroundStyle(Theme.muted)
                        .multilineTextAlignment(.center)
                }
                .padding(16)
                .containerBackground(Theme.bg, for: .widget)
            }
        }
        // After sunset the whole widget goes dark, like the picture.
        .environment(\.colorScheme, entry.data?.sun?.night == true ? .dark : scheme)
    }

    /// Just the picture, as tall as the widget; the sky and grass carry on either side of it.
    private func medium(_ data: EnergyOverview) -> some View {
        EnergyHouse(data: data, compact: true, sky: entry.sky)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .containerBackground(for: .widget) {
                GeometryReader { geo in
                    ZStack(alignment: .bottom) {
                        LinearGradient(colors: [EnergyColors.sky1, EnergyColors.sky2], startPoint: .top, endPoint: .bottom)
                        EnergyColors.grass.frame(height: geo.size.height / 6)
                    }
                }
            }
    }

    /// The picture, then the car's target and the cheap-rate times under it.
    private func large(_ data: EnergyOverview) -> some View {
        var items: [(String, String)] = []
        if let car = data.car, let target = Energy.carTarget(car) { items.append(("Car", target)) }
        items += Energy.planItems(data.plan, data.tariff, now: entry.date)
        items = Array(items.prefix(family == .systemLarge ? 4 : 6))
        return VStack(spacing: 10) {
            EnergyHouse(data: data, compact: family == .systemLarge, sky: entry.sky)
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], spacing: 8) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.0.uppercased()).font(.system(size: 10, weight: .heavy, design: .rounded))
                            .tracking(0.6).foregroundStyle(Theme.muted)
                        Text(item.1).font(.system(size: 14, weight: .heavy, design: .rounded)).foregroundStyle(Theme.text)
                            .lineLimit(2).minimumScaleFactor(0.8)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .containerBackground(Theme.bg, for: .widget)
    }
}

extension EnergyOverview {
    /// What the widget gallery shows before the first reading.
    static let sample: EnergyOverview = {
        let json = """
        {"configured": true, "reachable": true, "solar": {"power": 2400, "today": 8.6},
         "battery": {"soc": 76, "power": -900}, "grid": {"power": -300},
         "home": {"power": 1200}, "car": {"plugged_in": true, "charging": false, "soc": 54, "limit": 80},
         "heat_pump": {"running": true, "doing": "Heating", "power": 650},
         "tariff": {"cheap_now": false, "next": {"start": "2026-10-21T23:30:00Z", "end": "2026-10-22T05:30:00Z"}, "bonus": []}}
        """
        return try! JSONDecoder().decode(EnergyOverview.self, from: Data(json.utf8))
    }()
}
