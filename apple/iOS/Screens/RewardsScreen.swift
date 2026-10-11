import SwiftUI

/// Each child's stars and what they're saving for. Cards flow into as many columns as fit.
struct RewardsScreen: View {
    @Environment(AppModel.self) private var model
    @State private var rewards: [Reward] = []
    @State private var points: [Balance] = []
    @State private var ledgers: [String: [LedgerEntry]] = [:]
    @State private var pin: PinRequest?
    @State private var adding = false
    @State private var bonusFor: Person?
    @State private var redeemed = 0
    @State private var celebrating: Person?
    @State private var message: String?

    var body: some View {
        Page(title: "Rewards") { _ in
            ScrollView {
                if model.kids.isEmpty {
                    EmptyHint(text: "Children earn stars for chores and spend them here. Add a child in Settings › Family.").padding(.top, 40)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), spacing: 16, alignment: .top)], spacing: 16) {
                    ForEach(model.kids) { kidCard($0) }
                }
                .padding(16)
            }
            .refreshable { model.bump("points") }
        } tools: {
            ToolbarItem(placement: .primaryAction) {
                Button { adding = true } label: { Image(systemName: "plus") }.accessibilityLabel("New reward")
            }
        }
        .overlay { if let celebrating { CelebrationBurst(person: celebrating) } }
        .sensoryFeedback(.success, trigger: redeemed)
        .pinPrompt($pin)
        .alert(message ?? "", isPresented: Binding(get: { message != nil }, set: { if !$0 { message = nil } })) {}
        .task(id: model.rev("rewards", "points", "people")) {
            if let v = await model.call({ try await $0.rewards() }) { rewards = v }
            if let v = await model.call({ try await $0.points() }) { points = v }
            for kid in model.kids {
                if let v = await model.call({ try await $0.ledger(kid.id) }) { ledgers[kid.id] = v }
            }
        }
        .sheet(isPresented: $adding) { RewardEditor() }
        .sheet(item: $bonusFor) { kid in BonusSheet(kid: kid) { change, reason in
            pin = PinRequest(title: "\(change > 0 ? "Give" : "Take") \(abs(change)) stars") { p in
                try await model.api?.adjustPoints(kid.id, change: change, reason: reason, pin: p)
                model.bump("points")
            }
        } }
    }

    private func balance(_ kid: Person) -> Int { points.first { $0.person_id == kid.id }?.balance ?? 0 }

    private func kidCard(_ kid: Person) -> some View {
        let color = Color(hex: kid.color)
        let bal = balance(kid)
        let mine = rewards.filter { $0.person_id == nil || $0.person_id == kid.id }.sorted { $0.cost < $1.cost }
        return VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Avatar(person: kid, size: 52)
                VStack(alignment: .leading, spacing: 0) {
                    Text(kid.name).font(Theme.text(.title3, .heavy))
                    Label("\(bal) stars", systemImage: "star.fill").labelStyle(TintedLabel(tint: Theme.star))
                        .font(Theme.text(.headline, .heavy))
                }
                Spacer()
                Button("Bonus") { bonusFor = kid }.buttonStyle(.bordered).tint(color)
            }
            if mine.isEmpty { EmptyHint(text: "No rewards yet") }
            ForEach(mine) { r in rewardRow(r, kid: kid, balance: bal) }
            if let recent = ledgers[kid.id], !recent.isEmpty {
                Text("RECENT STARS").font(Theme.text(.caption2, .heavy)).kerning(1).foregroundStyle(Theme.muted).padding(.top, 6)
                ForEach(recent.prefix(5)) { l in
                    HStack {
                        Text(l.reason).font(Theme.text(.subheadline, .semibold)).lineLimit(1)
                        Spacer()
                        Text(l.change > 0 ? "+\(l.change)" : "\(l.change)").font(Theme.text(.subheadline, .heavy))
                            .foregroundStyle(l.change > 0 ? Theme.starText : Theme.muted)
                    }
                }
            }
        }
        .padding(16)
        .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private func rewardRow(_ r: Reward, kid: Person, balance: Int) -> some View {
        let color = Color(hex: kid.color)
        let affordable = balance >= r.cost
        return Button { redeem(r, kid: kid) } label: {
            HStack(spacing: 12) {
                Text(r.emoji.isEmpty ? "🎁" : r.emoji).font(.system(size: 30))
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(r.title).font(Theme.text(.subheadline, .heavy)).lineLimit(1)
                        Spacer()
                        Label("\(r.cost)", systemImage: "star.fill").labelStyle(TintedLabel(tint: Theme.star)).font(Theme.text(.caption, .heavy))
                    }
                    ProgressView(value: min(1, Double(balance) / Double(max(r.cost, 1))))
                        .tint(affordable ? Theme.star : color)
                    Text(affordable ? "Ready to redeem" : "\(r.cost - balance) more to go")
                        .font(Theme.text(.caption, .bold)).foregroundStyle(affordable ? Theme.starText : Theme.muted)
                }
            }
            .padding(12)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .foregroundStyle(Theme.text)
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button("Delete reward", systemImage: "trash", role: .destructive) {
                Task {
                    _ = await model.call { try await $0.deleteReward(r.id) }
                    model.bump("rewards")
                }
            }
        }
    }

    private func redeem(_ r: Reward, kid: Person) {
        guard balance(kid) >= r.cost else {
            message = "\(kid.name) needs \(r.cost - balance(kid)) more stars for \(r.title)."
            return
        }
        pin = PinRequest(title: "Spend \(r.cost) stars on \(r.title) for \(kid.name)?") { p in
            guard let api = model.api else { return }
            _ = try await api.redeem(r.id, personId: kid.id, pin: p)
            model.bump("points")
            redeemed += 1
            withAnimation(.spring) { celebrating = kid }
            try? await Task.sleep(for: .seconds(2))
            withAnimation { celebrating = nil }
        }
    }
}

struct BonusSheet: View {
    @Environment(\.dismiss) private var dismiss
    let kid: Person
    let onSave: (Int, String) -> Void
    @State private var change = 1
    @State private var reason = ""

    var body: some View {
        NavigationStack {
            Form {
                Stepper(value: $change, in: -50...50) {
                    Text(change >= 0 ? "Give \(change) star\(change == 1 ? "" : "s")" : "Take \(-change) star\(change == -1 ? "" : "s")")
                        .font(Theme.text(.headline))
                }
                TextField("Why? (e.g. Helped with the shopping)", text: $reason)
            }
            .navigationTitle("Stars for \(kid.name)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        dismiss()
                        onSave(change, reason.isEmpty ? (change > 0 ? "⭐ Bonus" : "Adjustment") : reason)
                    }
                    .disabled(change == 0)
                }
            }
        }
        .presentationDetents([.medium])
    }
}

struct RewardEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var emoji = ""
    @State private var cost = 10
    @State private var person: String = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                HStack {
                    TextField("🎁", text: $emoji).frame(width: 44).font(.system(size: 28))
                        .onChange(of: emoji) { if emoji.count > 1 { emoji = String(emoji.suffix(1)) } }
                    TextField("Reward", text: $title).font(Theme.text(.headline))
                }
                Stepper(value: $cost, in: 1...500) {
                    Label("\(cost) stars", systemImage: "star.fill").labelStyle(TintedLabel(tint: Theme.star))
                }
                Picker("For", selection: $person) {
                    Text("Any child").tag("")
                    ForEach(model.kids) { Text($0.name).tag($0.id) }
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle("New reward")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            do {
                                try await model.api?.createReward(title: title, emoji: emoji, cost: cost, personId: person.isEmpty ? nil : person)
                                model.bump("rewards")
                                dismiss()
                            } catch { self.error = error.localizedDescription }
                        }
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}
