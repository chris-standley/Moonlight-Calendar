import SwiftUI

/// Nursery updates from Tapestry (through Moonlight): the updates down the side, the chosen one in full. Select a
/// photo to see it full screen.
struct NurseryView: View {
    @Environment(AppModel.self) private var model
    @State private var updates: [NurseryUpdate] = []
    @State private var config: NurseryConfig?
    @State private var selected: String?
    @State private var viewing: Viewing?

    struct Viewing: Identifiable {
        let update: NurseryUpdate
        let start: Int
        var id: String { "\(update.id)-\(start)" }
    }

    var body: some View {
        let current = updates.first { $0.id == selected } ?? updates.first
        Screen {
            HStack(alignment: .firstTextBaseline, spacing: 20) {
                Text("Nursery").font(Theme.font(40, .heavy)).foregroundStyle(Theme.text)
                if let name = config?.school_name {
                    Text(name).font(Theme.font(28, .bold)).foregroundStyle(Theme.muted)
                }
            }
            if updates.isEmpty {
                FamilyPrompt(text: config?.configured == true
                             ? "No updates from nursery yet."
                             : "Connect Tapestry in Moonlight Settings › Nursery on a wall screen, and nursery updates appear here.")
            } else {
                HStack(alignment: .top, spacing: 36) {
                    ScrollView {
                        VStack(spacing: 14) {
                            ForEach(updates) { u in row(u, on: u.id == current?.id) }
                        }
                        .padding(14)
                    }
                    .scrollClipDisabled()
                    .frame(width: 560)
                    .focusSection()

                    if let current { detail(current).focusSection() }
                }
                .padding(.bottom, 40)
            }
        }
        .task(id: model.rev("nursery")) {
            config = await model.call { try await $0.nursery() }
            if config?.configured == true, let v = await model.call({ try await $0.nurseryUpdates() }) { updates = v } else { updates = [] }
        }
        .fullScreenCover(item: $viewing) { v in NurseryPhotos(update: v.update, index: v.start) }
    }

    private func row(_ u: NurseryUpdate, on: Bool) -> some View {
        Button { selected = u.id } label: {
            HStack(spacing: 18) {
                RemoteImage(path: u.photos.first?.url)
                    .frame(width: 120, height: 120)
                    .background(Theme.surface2)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                VStack(alignment: .leading, spacing: 6) {
                    Text(u.title).font(Theme.font(26, .heavy)).foregroundStyle(Theme.text).lineLimit(2)
                    Text(u.whenText(today: model.dates.today)).font(Theme.font(20, .bold)).foregroundStyle(Theme.muted)
                }
                Spacer(minLength: 0)
            }
            .padding(14)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay {
                if on { RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Theme.accent, lineWidth: 4) }
            }
        }
        .buttonStyle(.moonCard(radius: 20))
    }

    private func detail(_ u: NurseryUpdate) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 14) {
                    ForEach(u.children, id: \.name) { k in
                        Text(k.name.split(separator: " ").first.map(String.init) ?? k.name)
                            .font(Theme.font(22, .heavy))
                            .foregroundStyle(k.color == nil ? Theme.text : .white)
                            .padding(.horizontal, 16).padding(.vertical, 6)
                            .background(k.color.map { Color(hex: $0) } ?? Theme.surface2, in: Capsule())
                    }
                    Text(u.whenText(today: model.dates.today) + (u.author.isEmpty ? "" : " · \(u.author)"))
                        .font(Theme.font(22, .bold)).foregroundStyle(Theme.muted)
                }
                Text(u.title).font(Theme.font(44, .heavy)).foregroundStyle(Theme.text)
                if !u.notes.isEmpty {
                    // Focusable so the remote can scroll a long note.
                    Text(u.notes).font(Theme.font(28, .semibold)).foregroundStyle(Theme.text.opacity(0.85))
                        .lineSpacing(6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .focusable()
                }
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 20), GridItem(.flexible(), spacing: 20)], spacing: 20) {
                    ForEach(Array(u.photos.enumerated()), id: \.offset) { i, p in
                        Button { viewing = Viewing(update: u, start: i) } label: {
                            RemoteImage(path: p.url)
                                .frame(height: 380)
                                .frame(maxWidth: .infinity)
                                .background(Theme.surface2)
                                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                                .overlay {
                                    if p.video {
                                        Image(systemName: "play.fill").font(.system(size: 44)).foregroundStyle(.white)
                                            .padding(28).background(.black.opacity(0.5), in: Circle())
                                    }
                                }
                        }
                        .buttonStyle(.moonCard(radius: 18))
                    }
                }
                ForEach(Array(u.comments.enumerated()), id: \.offset) { _, c in
                    (Text(c.author.isEmpty ? "" : c.author + "  ").font(Theme.font(24, .heavy)) + Text(c.text).font(Theme.font(24, .semibold)))
                        .foregroundStyle(Theme.text)
                        .padding(20)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                }
            }
            .padding(36)
        }
        .clipTopAndBottom()
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
    }
}

/// An update's photos full screen: left and right to move, Menu to go back.
struct NurseryPhotos: View {
    @Environment(\.dismiss) private var dismiss
    let update: NurseryUpdate
    @State var index: Int

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Color.black.ignoresSafeArea()
            if !update.photos.isEmpty {
                RemoteImage(path: update.photos[index % update.photos.count].url, contentMode: .fit)
                    .id(index)
                    .transition(.opacity)
                    .ignoresSafeArea()
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(update.title).font(Theme.font(40, .heavy))
                if update.photos.count > 1 {
                    Text("\(index + 1) of \(update.photos.count)").font(Theme.font(26, .bold)).opacity(0.8)
                }
            }
            .foregroundStyle(.white)
            .shadow(color: .black.opacity(0.6), radius: 12)
            .padding(70)
        }
        .focusable()
        .onMoveCommand { dir in
            guard update.photos.count > 1 else { return }
            let n = update.photos.count
            withAnimation(.easeInOut(duration: 0.5)) {
                if dir == .right { index = (index + 1) % n }
                if dir == .left { index = (index - 1 + n) % n }
            }
        }
        .onExitCommand { dismiss() }
    }
}
