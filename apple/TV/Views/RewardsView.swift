import SwiftUI

/// Each child's stars, the rewards they're saving for, and recent stars. Redeeming asks for the parent PIN
/// on an on-screen number pad (no keyboard).
struct RewardsView: View {
    @Environment(AppModel.self) private var model
    @State private var rewards: [Reward] = []
    @State private var points: [Balance] = []
    @State private var ledgers: [String: [LedgerEntry]] = [:]
    @State private var redeeming: Redeem?
    @State private var celebrating: Person?

    struct Redeem: Identifiable {
        let reward: Reward
        let kid: Person
        var id: String { reward.id + kid.id }
    }

    var body: some View {
        Screen {
            if model.kids.isEmpty {
                FamilyPrompt(text: "Children earn stars for chores and spend them here. Add a child in Moonlight Settings › Family to get started.")
            } else {
                HStack(alignment: .top, spacing: 24) {
                    ForEach(model.kids) { kid in column(kid) }
                }
                .padding(.bottom, 40)
            }
        }
        .overlay { if let celebrating { Celebration(person: celebrating) } }
        .task(id: model.rev("rewards", "points", "people")) {
            if let v = await model.call({ try await $0.rewards() }) { rewards = v }
            if let v = await model.call({ try await $0.points() }) { points = v }
            for kid in model.kids {
                if let v = await model.call({ try await $0.ledger(kid.id) }) { ledgers[kid.id] = v }
            }
        }
        .sheet(item: $redeeming) { r in
            PinPad(title: "Spend \(r.reward.cost) stars on \(r.reward.emoji) \(r.reward.title) for \(r.kid.name)?",
                   needsPin: model.settings?.pin_set ?? true) { pin in
                try await redeem(r, pin: pin)
            }
        }
    }

    private func balance(_ kid: Person) -> Int { points.first { $0.person_id == kid.id }?.balance ?? 0 }

    private func column(_ kid: Person) -> some View {
        let color = Color(hex: kid.color)
        let bal = balance(kid)
        let mine = rewards.filter { $0.person_id == nil || $0.person_id == kid.id }.sorted { $0.cost < $1.cost }
        return VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 18) {
                Avatar(person: kid, size: 84)
                VStack(alignment: .leading, spacing: 2) {
                    Text(kid.name).font(Theme.font(34, .heavy)).foregroundStyle(Theme.text)
                    HStack(spacing: 8) {
                        Image(systemName: "star.fill").foregroundStyle(Theme.star)
                        Text("\(bal) stars").foregroundStyle(Theme.starText)
                    }
                    .font(Theme.font(30, .heavy))
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if mine.isEmpty { EmptyNote(text: "No rewards yet") }
                    ForEach(mine) { r in rewardRow(r, kid: kid, balance: bal) }
                    if let recent = ledgers[kid.id], !recent.isEmpty {
                        Text("RECENT STARS").font(Theme.font(19, .heavy)).kerning(1.2).foregroundStyle(Theme.muted).padding(.top, 16)
                        ForEach(recent.prefix(6)) { l in
                            HStack {
                                Text(l.reason).font(Theme.font(22, .bold)).foregroundStyle(Theme.text).lineLimit(1)
                                Spacer()
                                Text(l.change > 0 ? "+\(l.change)" : "\(l.change)")
                                    .font(Theme.font(22, .heavy))
                                    .foregroundStyle(l.change > 0 ? Theme.starText : Theme.muted)
                            }
                            .padding(.horizontal, 6)
                        }
                    }
                }
                .padding(.horizontal, 6).padding(.vertical, 10)
            }
            .scrollClipDisabled()
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .focusSection()
    }

    private func rewardRow(_ r: Reward, kid: Person, balance: Int) -> some View {
        let color = Color(hex: kid.color)
        let progress = min(1, Double(balance) / Double(max(r.cost, 1)))
        let affordable = balance >= r.cost
        return Button { redeeming = Redeem(reward: r, kid: kid) } label: {
            HStack(spacing: 18) {
                Text(r.emoji).font(.system(size: 46))
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(r.title).font(Theme.font(26, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                        Spacer()
                        Label("\(r.cost)", systemImage: "star.fill").labelStyle(StarLabelStyle()).font(Theme.font(22, .heavy))
                    }
                    GeometryReader { g in
                        ZStack(alignment: .leading) {
                            Capsule().fill(color.opacity(0.18))
                            Capsule().fill(affordable ? Theme.star : color).frame(width: g.size.width * progress)
                        }
                    }
                    .frame(height: 12)
                    Text(affordable ? "Ready to redeem!" : "\(r.cost - balance) more to go")
                        .font(Theme.font(19, .bold)).foregroundStyle(affordable ? Theme.starText : Theme.muted)
                }
            }
            .padding(18)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .buttonStyle(.moonCard(radius: 18, ring: color))
        .disabled(!affordable)
    }

    private func redeem(_ r: Redeem, pin: String) async throws {
        guard let api = model.api else { return }
        _ = try await api.redeem(r.reward.id, personId: r.kid.id, pin: pin)
        redeeming = nil
        model.bump("points")
        withAnimation(.spring) { celebrating = r.kid }
        try? await Task.sleep(for: .seconds(2.5))
        withAnimation { celebrating = nil }
    }
}

/// A number pad for the parent PIN, driven by the remote. With no PIN set it's a plain confirm.
struct PinPad: View {
    let title: String
    let needsPin: Bool
    let onSubmit: (String) async throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var pin = ""
    @State private var error: String?
    @State private var busy = false

    private let keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]

    var body: some View {
        VStack(spacing: 34) {
            Text(title).font(Theme.font(40, .heavy)).multilineTextAlignment(.center).frame(maxWidth: 900)
            if needsPin {
                Text("Enter the parent PIN").font(Theme.font(28, .bold)).foregroundStyle(Theme.muted)
                HStack(spacing: 20) {
                    ForEach(0..<max(4, pin.count), id: \.self) { i in
                        Circle().fill(i < pin.count ? Theme.accent : Theme.line).frame(width: 28, height: 28)
                    }
                }
                LazyVGrid(columns: Array(repeating: GridItem(.fixed(150), spacing: 24), count: 3), spacing: 24) {
                    ForEach(keys, id: \.self) { k in
                        Button { press(k) } label: {
                            Text(k).font(Theme.font(44, .heavy)).frame(width: 150, height: 100)
                        }
                        .buttonStyle(.bordered)
                        .disabled(busy || (k == "OK" && pin.isEmpty))
                    }
                }
            } else {
                HStack(spacing: 30) {
                    Button("Cancel") { dismiss() }.buttonStyle(.pill)
                    Button("Redeem") { submit() }.buttonStyle(.pillProminent).disabled(busy)
                }
            }
            Text(error ?? " ").font(Theme.font(26, .bold)).foregroundStyle(Theme.danger)
        }
        .padding(60)
    }

    private func press(_ k: String) {
        error = nil
        switch k {
        case "⌫": if !pin.isEmpty { pin.removeLast() }
        case "OK": submit()
        default: if pin.count < 8 { pin.append(k) }
        }
    }

    private func submit() {
        busy = true
        Task {
            defer { busy = false }
            do {
                try await onSubmit(pin)
            } catch {
                self.error = error.localizedDescription
                pin = ""
            }
        }
    }
}
