import SwiftUI

/// Toolbar button on Today for nursery updates from Tapestry, with how many are new on this device. Hidden until
/// Tapestry is connected (Settings › Nursery on a wall screen).
struct NurseryButton: View {
    @Environment(AppModel.self) private var model
    @AppStorage("nurserySeen") private var seen = ""
    @State private var configured = false
    @State private var updates: [NurseryUpdate] = []
    @State private var open = false

    /// On a phone that has never opened them, the last few days' updates count as new.
    private var since: String { seen.isEmpty ? model.dates.addDays(model.dates.today, -3) : seen }
    private var unread: Int { updates.filter { $0.date > since }.count }

    var body: some View {
        Group {
            if configured {
                Button { open = true } label: {
                    Image(systemName: "figure.and.child.holdinghands")
                        .overlay(alignment: .topTrailing) {
                            if unread > 0 {
                                Text(unread > 9 ? "9+" : "\(unread)")
                                    .font(.caption2.weight(.heavy)).foregroundStyle(.white)
                                    .padding(.horizontal, 5).padding(.vertical, 1)
                                    .background(Theme.danger, in: Capsule())
                                    .offset(x: 10, y: -8)
                            }
                        }
                }
                .accessibilityLabel(unread > 0 ? "Nursery updates, \(unread) new" : "Nursery updates")
            }
        }
        .task(id: model.rev("nursery")) {
            let config = await model.call { try await $0.nursery() }
            configured = config?.configured ?? false
            if configured, let v = await model.call({ try await $0.nurseryUpdates() }) { updates = v } else if !configured { updates = [] }
        }
        .sheet(isPresented: $open, onDismiss: { if let newest = updates.first?.date, newest > since { seen = newest } }) {
            NurserySheet(updates: updates)
        }
    }
}

struct NurserySheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let updates: [NurseryUpdate]
    @State private var viewing: NurseryUpdate.Picture?

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    if updates.isEmpty { EmptyHint(text: "No updates from nursery yet.") }
                    ForEach(updates) { u in card(u) }
                }
                .padding(16)
            }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Nursery")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .fullScreenCover(item: $viewing) { p in
            ZStack(alignment: .topTrailing) {
                Color.black.ignoresSafeArea()
                RemoteImage(path: p.url, contentMode: .fit).frame(maxWidth: .infinity, maxHeight: .infinity)
                Button { viewing = nil } label: {
                    Image(systemName: "xmark.circle.fill").font(.largeTitle).foregroundStyle(.white.opacity(0.85))
                }
                .padding()
                .accessibilityLabel("Close")
            }
            .onTapGesture { viewing = nil }
        }
    }

    private func card(_ u: NurseryUpdate) -> some View {
        Card {
            HStack(spacing: 8) {
                ForEach(u.children, id: \.name) { k in
                    Text(k.name.split(separator: " ").first.map(String.init) ?? k.name)
                        .font(Theme.text(.caption, .heavy))
                        .foregroundStyle(k.color == nil ? Theme.text : .white)
                        .padding(.horizontal, 10).padding(.vertical, 3)
                        .background(k.color.map { Color(hex: $0) } ?? Theme.surface2, in: Capsule())
                }
                Text(u.whenText(today: model.dates.today) + (u.author.isEmpty ? "" : " · \(u.author)"))
                    .font(Theme.text(.caption)).foregroundStyle(Theme.muted)
            }
            Text(u.title).font(Theme.text(.title3, .heavy)).foregroundStyle(Theme.text)
            if !u.notes.isEmpty {
                Text(u.notes).font(Theme.text(.body, .regular)).foregroundStyle(Theme.text.opacity(0.85)).textSelection(.enabled)
            }
            if !u.photos.isEmpty {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 8)], spacing: 8) {
                    ForEach(u.photos, id: \.url) { p in
                        Button { viewing = p } label: {
                            Color.clear.aspectRatio(4 / 3, contentMode: .fit)
                                .overlay { RemoteImage(path: p.url) }
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .overlay {
                                    if p.video {
                                        Image(systemName: "play.fill").foregroundStyle(.white)
                                            .padding(12).background(.black.opacity(0.5), in: Circle())
                                    }
                                }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            ForEach(Array(u.comments.enumerated()), id: \.offset) { _, c in
                (Text(c.author.isEmpty ? "" : c.author + "  ").bold() + Text(c.text))
                    .font(Theme.text(.subheadline, .regular))
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }
}

extension NurseryUpdate.Picture: Identifiable {
    var id: String { url }
}
