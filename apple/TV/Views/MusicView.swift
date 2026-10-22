import SwiftUI

/// Music on the TV, for its speaker (Settings › Screens): what's playing with the controls and volume, beside Up next,
/// Library (albums, playlists, podcasts... picked with the remote; play now, next or at the end of the queue) and
/// Rooms (group speakers, each room's volume). No text entry, so no search here.
struct MusicView: View {
    @Environment(AppModel.self) private var model
    @State private var np: NowPlaying?
    @State private var fetched = Date()
    @State private var pane = "queue"
    @State private var chose = false

    var body: some View {
        Screen {
            HStack(alignment: .top, spacing: 48) {
                NowPlayingColumn(np: np, fetched: fetched, reload: load)
                    .frame(width: 600)
                    .focusSection()
                VStack(alignment: .leading, spacing: 24) {
                    HStack(spacing: 16) {
                        paneButton("queue", "Up next", "list.bullet")
                        paneButton("library", "Library", "music.note.list")
                        paneButton("rooms", "Rooms", "hifispeaker.2")
                    }
                    .focusSection()
                    switch pane {
                    case "library": TVLibrary()
                    case "rooms": TVRooms()
                    default: TVQueue()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .padding(.top, 70)
        }
        .task(id: model.rev("media", "settings")) { await load() }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await load()
            }
        }
    }

    private func paneButton(_ id: String, _ title: String, _ symbol: String) -> some View {
        Button { pane = id; chose = true } label: {
            Label(title, systemImage: symbol).font(Theme.font(26, .heavy))
        }
        .buttonStyle(.bordered)
        .tint(pane == id ? Theme.accent : nil)
    }

    private func load() async {
        if let v = await model.call({ try await $0.nowPlaying() }) {
            np = v
            fetched = Date()
            if !chose { pane = v.show ? "queue" : "library" }
        }
    }
}

private struct NowPlayingColumn: View {
    @Environment(AppModel.self) private var model
    let np: NowPlaying?
    let fetched: Date
    let reload: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            if let np, np.show {
                RemoteImage(path: np.art_url)
                    .frame(width: 440, height: 440)
                    .background(Color.white.opacity(0.1))
                    .overlay { if np.art_url == nil { Image(systemName: "music.note").font(.system(size: 90)).opacity(0.6) } }
                    .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
                    .shadow(color: .black.opacity(0.35), radius: 30, y: 16)
                    .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 6) {
                    Text((np.name ?? "Speaker").uppercased()).font(Theme.font(20, .heavy)).tracking(1).opacity(0.7)
                    Text(np.title ?? "Unknown track").font(Theme.font(38, .heavy)).lineLimit(2)
                    let detail = [np.artist, np.album].compactMap { $0 }.joined(separator: " · ")
                    if !detail.isEmpty { Text(detail).font(Theme.font(26, .bold)).opacity(0.8).lineLimit(2) }
                }
                if let duration = np.duration, duration > 0 {
                    TimelineView(.periodic(from: .now, by: 1)) { ctx in
                        let pos = np.position(at: ctx.date, fetched: fetched) ?? 0
                        VStack(spacing: 6) {
                            ProgressView(value: min(pos, duration), total: duration).tint(.white)
                            HStack { Text(trackTime(pos)); Spacer(); Text("-" + trackTime(duration - pos)) }
                                .font(Theme.font(20, .bold)).monospacedDigit().opacity(0.7)
                        }
                    }
                }
                HStack(spacing: 22) {
                    control("backward.fill", enabled: np.supports?.previous ?? true) { await act("previous") }
                    control(np.isPlaying ? "pause.fill" : "play.fill", big: true) { await act("play_pause") }
                    control("forward.fill", enabled: np.supports?.next ?? true) { await act("next") }
                }
                .frame(maxWidth: .infinity)
                if np.supports?.volume == true, let v = np.volume {
                    HStack(spacing: 18) {
                        control("speaker.minus.fill") { await act("volume_set", max(0, v - 0.05)) }
                        Text("\(Int((np.muted == true ? 0 : v) * 100))%").font(Theme.font(26, .heavy)).monospacedDigit().frame(width: 100)
                        control("speaker.plus.fill") { await act("volume_set", min(1, v + 0.05)) }
                    }
                    .frame(maxWidth: .infinity)
                }
            } else {
                VStack(spacing: 16) {
                    Image(systemName: "music.note").font(.system(size: 80)).opacity(0.7)
                    Text("Nothing playing").font(Theme.font(34, .heavy))
                    Text("Pick something from the library.").font(Theme.font(24, .bold)).opacity(0.75)
                }
                .frame(maxWidth: .infinity, minHeight: 500)
            }
        }
        .foregroundStyle(.white)
        .padding(34)
        .background {
            ZStack {
                Color(hex: "#17182A")
                if let np, np.show, np.art_url != nil { RemoteImage(path: np.art_url).blur(radius: 60).opacity(0.45) }
            }
            .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        }
    }

    private func control(_ symbol: String, enabled: Bool = true, big: Bool = false, _ run: @escaping () async -> Void) -> some View {
        Button { Task { await run() } } label: {
            Image(systemName: symbol)
                .font(.system(size: big ? 34 : 26, weight: .bold))
                .frame(width: big ? 86 : 70, height: big ? 86 : 70)
        }
        .buttonStyle(.bordered)
        .clipShape(Circle())
        .disabled(!enabled)
    }

    private func act(_ action: String, _ value: Any? = nil) async {
        if let value {
            _ = await model.call { try await $0.media(action, value: value) }
        } else {
            _ = await model.call { try await $0.media(action) }
        }
        await reload()
    }
}

// MARK: Up next

private struct TVQueue: View {
    @Environment(AppModel.self) private var model
    @State private var queue: MediaQueue?
    @State private var picked: QueueTrack?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                if let q = queue {
                    if q.items.isEmpty {
                        EmptyNote(text: "The queue is empty. Pick something from the library.")
                    }
                    ForEach(q.items) { t in
                        Button { if !t.current && (q.can_jump || q.can_remove || q.can_move) { picked = t } } label: {
                            TVRow(title: t.title, detail: t.detail, thumb: t.thumb, trailing: t.current ? nil : trackTime(t.duration), current: t.current)
                        }
                        .buttonStyle(CardButtonStyle())
                    }
                    if !q.full && q.source == "music_assistant" {
                        Text("Connect Music Assistant in Settings › Music on a wall screen to see the whole queue.")
                            .font(Theme.font(20, .bold)).foregroundStyle(Theme.muted).padding(.top, 8)
                    }
                }
            }
            .padding(.vertical, 10)
        }
        .clipTopAndBottom()
        .focusSection()
        .confirmationDialog(picked?.title ?? "", isPresented: Binding(get: { picked != nil }, set: { if !$0 { picked = nil } }), titleVisibility: .visible) {
            if let t = picked, let q = queue {
                if q.can_jump { Button("Play now") { act(t, "play") } }
                if q.can_move { Button("Play next") { act(t, "next") } }
                if q.can_remove { Button("Remove from queue", role: .destructive) { act(t, "remove") } }
            }
        }
        .task(id: model.rev("media")) { queue = await model.call { try await $0.mediaQueue() } }
    }

    private func act(_ t: QueueTrack, _ action: String) {
        Task {
            _ = await model.call { try await $0.queueAction(action, key: t.key) }
            queue = await model.call { try await $0.mediaQueue() }
        }
    }
}

private struct TVRow: View {
    let title: String
    let detail: String?
    let thumb: String?
    let trailing: String?
    let current: Bool

    var body: some View {
        HStack(spacing: 20) {
            TVThumb(path: thumb).frame(width: 76, height: 76)
            VStack(alignment: .leading, spacing: 4) {
                Text(title.isEmpty ? "Unknown track" : title).font(Theme.font(26, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                if let detail { Text(detail).font(Theme.font(20, .bold)).foregroundStyle(Theme.muted).lineLimit(1) }
            }
            Spacer(minLength: 0)
            if current {
                Image(systemName: "waveform").font(.system(size: 28)).foregroundStyle(Theme.accent)
            } else if let trailing, !trailing.isEmpty {
                Text(trailing).font(Theme.font(22, .bold)).monospacedDigit().foregroundStyle(Theme.muted)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(current ? Theme.accent.opacity(0.14) : Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

private struct TVThumb: View {
    let path: String?
    var round = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: "#3A3F62"), Color(hex: "#5A4F82")], startPoint: .topLeading, endPoint: .bottomTrailing)
            Image(systemName: "music.note").font(.system(size: 28)).foregroundStyle(.white.opacity(0.7))
            RemoteImage(path: path)
        }
        .clipShape(round ? AnyShape(Circle()) : AnyShape(RoundedRectangle(cornerRadius: 12, style: .continuous)))
    }
}

// MARK: Library

private let firstSections = ["albums", "playlists", "podcasts", "radio", "artists", "audiobooks", "tracks"]

private struct TVLibrary: View {
    @Environment(AppModel.self) private var model
    @State private var sections: [MediaItem] = []
    /// Where we are: a section, then any album, playlist or podcast opened from it.
    @State private var path: [MediaItem] = []
    @State private var page: MediaBrowse?
    @State private var picked: MediaItem?
    @State private var failed: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if path.count > 1, let here = path.last {
                HStack(spacing: 20) {
                    Button { path.removeLast() } label: { Image(systemName: "chevron.left") }
                    TVThumb(path: page?.thumb ?? here.thumb).frame(width: 90, height: 90)
                    VStack(alignment: .leading) {
                        Text(here.title).font(Theme.font(30, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                        if let sub = here.subtitle { Text(sub).font(Theme.font(22, .bold)).foregroundStyle(Theme.muted) }
                    }
                    Spacer()
                    if here.can_play {
                        Button("Play") { play(here, "replace") }
                        Button("Next") { play(here, "next") }
                        Button("Queue") { play(here, "add") }
                    }
                }
                .focusSection()
            } else if sections.count > 1 {
                ScrollView(.horizontal) {
                    HStack(spacing: 14) {
                        ForEach(sections, id: \.id) { s in
                            Button(s.title) { path = [s] }
                                .tint(path.first?.id == s.id ? Theme.accent : nil)
                        }
                    }
                    .padding(.vertical, 12)
                }
                .scrollClipDisabled()
                .focusSection()
            }
            if let failed {
                EmptyNote(text: failed)
            } else if let page, page.id == path.last?.id {
                ScrollView {
                    if page.items.isEmpty { EmptyNote(text: "Nothing here yet.") }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 32)], spacing: 36) {
                        ForEach(Array(page.items.enumerated()), id: \.offset) { _, item in
                            Button { choose(item) } label: { tile(item) }
                                .buttonStyle(CardButtonStyle())
                        }
                    }
                    .padding(20)
                }
                .clipTopAndBottom()
                .focusSection()
            } else {
                ProgressView().frame(maxWidth: .infinity).padding(60)
            }
        }
        .onExitCommand(perform: path.count > 1 ? { path.removeLast() } : nil)
        .confirmationDialog(picked?.title ?? "", isPresented: Binding(get: { picked != nil }, set: { if !$0 { picked = nil } }), titleVisibility: .visible) {
            if let item = picked {
                if item.can_play {
                    Button("Play now") { play(item, "replace") }
                    Button("Play next") { play(item, "next") }
                    Button("Add to queue") { play(item, "add") }
                }
                if item.can_expand { Button("Open") { path.append(item) } }
            }
        }
        .task { await loadTop() }
        .task(id: path.last?.id) {
            guard let here = path.last else { return }
            page = await model.call { try await $0.browse(here) }
        }
    }

    private func tile(_ item: MediaItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            TVThumb(path: item.thumb, round: item.kind == "artist").frame(width: 220, height: 220)
            Text(item.title).font(Theme.font(22, .heavy)).foregroundStyle(Theme.text).lineLimit(2)
                .frame(width: 220, alignment: .leading)
            if let sub = item.subtitle { Text(sub).font(Theme.font(18, .bold)).foregroundStyle(Theme.muted).lineLimit(1).frame(width: 220, alignment: .leading) }
        }
        .padding(10)
    }

    /// A folder with nothing to play opens; anything playable asks how (and offers Open when it's a folder too).
    private func choose(_ item: MediaItem) {
        if item.can_expand && !item.can_play { path.append(item) } else { picked = item }
    }

    private func play(_ item: MediaItem, _ enqueue: String) {
        Task {
            _ = await model.call { try await $0.play(item, enqueue: enqueue) }
            model.bump("media")
        }
    }

    private func loadTop() async {
        guard sections.isEmpty, let api = model.api else { return }
        do {
            var top = try await api.browse(nil)
            if top.items.count == 1, top.items[0].can_expand { top = try await api.browse(top.items[0]) }
            let rank = { (i: MediaItem) in firstSections.firstIndex(of: i.id) ?? 99 }
            sections = top.items.filter(\.can_expand).sorted { rank($0) < rank($1) }
            if let first = sections.first { path = [first] }
        } catch {
            failed = error.localizedDescription
        }
    }
}

// MARK: Rooms

private struct TVRooms: View {
    @Environment(AppModel.self) private var model
    @State private var rooms: MediaRooms?

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                if let r = rooms {
                    if !r.can_group { EmptyNote(text: "This speaker can't play in a group from Moonlight. Each room's volume still works.") }
                    ForEach(r.rooms) { room in
                        HStack(spacing: 18) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(room.name).font(Theme.font(28, .heavy)).foregroundStyle(Theme.text)
                                Text(room.this ? "This speaker" : room.playing.map { "Playing \($0)" } ?? (room.grouped ? "In this group" : "Not playing"))
                                    .font(Theme.font(20, .bold)).foregroundStyle(Theme.muted).lineLimit(1)
                            }
                            Spacer()
                            if room.can_volume, let v = room.volume {
                                Button { act(room, "volume", max(0, v - 0.05)) } label: { Image(systemName: "speaker.minus.fill") }
                                Text("\(Int((room.muted == true ? 0 : v) * 100))%").font(Theme.font(24, .heavy)).monospacedDigit().frame(width: 90)
                                Button { act(room, "volume", min(1, v + 0.05)) } label: { Image(systemName: "speaker.plus.fill") }
                            }
                            if !room.this && r.can_group {
                                Button { act(room, room.grouped ? "unjoin" : "join", nil) } label: {
                                    Label(room.grouped ? "In group" : "Add", systemImage: room.grouped ? "checkmark" : "plus")
                                }
                                .tint(room.grouped ? Theme.accent : nil)
                            }
                        }
                        .padding(20)
                        .background(room.grouped ? Theme.accent.opacity(0.14) : Theme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                        .focusSection()
                    }
                }
            }
            .padding(.vertical, 10)
        }
        .clipTopAndBottom()
        .task(id: model.rev("media")) { rooms = await model.call { try await $0.rooms() } }
    }

    private func act(_ room: MediaRoom, _ action: String, _ value: Any?) {
        Task {
            if let r = await model.call({ try await $0.roomAction(room.entity_id, action, value: value) }) { rooms = r }
        }
    }
}
