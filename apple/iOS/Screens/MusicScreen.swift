import SwiftUI

/// Music: the speaker set for phones in Settings › Screens (as on the wall screens): what's playing with the controls
/// and volume, then Up next (the queue), Library (browse and search; play now, next or at the end of the queue) and
/// Rooms (group speakers, each room's volume). Only in the tab bar when there is a speaker.
struct MusicScreen: View {
    @Environment(AppModel.self) private var model
    @State private var np: NowPlaying?
    @State private var fetched = Date()
    @State private var pane = MusicPane.queue
    @State private var chose = false

    var body: some View {
        Page(title: "Music") { room in
            Group {
                if room == .narrow {
                    ScrollView {
                        VStack(spacing: 14) {
                            NowPlayingPanel(np: np, fetched: fetched, compact: true, reload: load)
                            panes
                        }
                        .padding(16)
                    }
                } else {
                    HStack(alignment: .top, spacing: 16) {
                        ScrollView { NowPlayingPanel(np: np, fetched: fetched, compact: false, reload: load) }
                            .frame(maxWidth: room == .wide ? 520 : 380)
                        ScrollView { panes }
                    }
                    .padding(16)
                }
            }
            // Albums, playlists and podcasts open as their own page.
            .navigationDestination(for: MediaItem.self) { LibraryFolder(folder: $0) }
        } tools: {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("Refresh")
            }
        }
        .task(id: model.rev("media", "settings")) { await load() }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await load()
            }
        }
    }

    private var panes: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Show", selection: Binding(get: { pane }, set: { pane = $0; chose = true })) {
                ForEach(MusicPane.allCases) { Label($0.title, systemImage: $0.symbol).tag($0) }
            }
            .pickerStyle(.segmented)
            switch pane {
            case .queue: QueuePane(onLibrary: { pane = .library; chose = true })
            case .library: LibraryPane(musicAssistant: np?.music_assistant == true)
            case .rooms: RoomsPane()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func load() async {
        if let v = await model.call({ try await $0.nowPlaying() }) {
            np = v
            fetched = Date()
            if !chose { pane = v.show ? .queue : .library }
        }
    }
}

enum MusicPane: String, CaseIterable, Identifiable {
    case queue, library, rooms
    var id: String { rawValue }
    var title: String { self == .queue ? "Up next" : rawValue.capitalized }
    var symbol: String { self == .queue ? "list.bullet" : self == .library ? "music.note.list" : "hifispeaker.2" }
}

// MARK: Now playing

private struct NowPlayingPanel: View {
    @Environment(AppModel.self) private var model
    let np: NowPlaying?
    let fetched: Date
    let compact: Bool
    let reload: () async -> Void
    @State private var volume: Double?
    @State private var sent = Date.distantPast

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let np, np.show {
                if compact {
                    HStack(spacing: 14) {
                        art(np).frame(width: 96, height: 96)
                        titles(np)
                    }
                } else {
                    art(np).frame(maxWidth: 420).aspectRatio(1, contentMode: .fit).frame(maxWidth: .infinity)
                    titles(np)
                }
                progress(np)
                controls(np)
                if np.supports?.volume == true, let v = np.volume { volumeRow(v, muted: np.muted == true) }
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "music.note").font(.system(size: 40)).foregroundStyle(.white.opacity(0.75))
                    Text("Nothing playing").font(Theme.text(.title3, .heavy))
                    Text(np?.configured == true ? "Pick something from the library." : "Choose a speaker for phones in Settings › Screens on a wall screen.")
                        .font(Theme.text(.subheadline)).opacity(0.75).multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 24)
            }
        }
        .foregroundStyle(.white)
        .padding(18)
        .background {
            ZStack {
                Color(hex: "#17182A")
                if let np, np.show, np.art_url != nil {
                    RemoteImage(path: np.art_url).blur(radius: 40).opacity(0.45)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
        .onChange(of: np?.volume) { volume = nil }
    }

    private func art(_ np: NowPlaying) -> some View {
        RemoteImage(path: np.art_url)
            .background(Color.white.opacity(0.12))
            .overlay { if np.art_url == nil { Image(systemName: "music.note").font(.system(size: 34)).opacity(0.7) } }
            .clipShape(RoundedRectangle(cornerRadius: compact ? 12 : 18, style: .continuous))
    }

    private func titles(_ np: NowPlaying) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(np.name ?? "Speaker", systemImage: "hifispeaker").font(Theme.text(.caption, .heavy)).textCase(.uppercase).opacity(0.7)
            Text(np.title ?? "Unknown track").font(Theme.text(compact ? .headline : .title2, .heavy)).lineLimit(2)
            let detail = [np.artist, np.album].compactMap { $0 }.joined(separator: " · ")
            if !detail.isEmpty { Text(detail).font(Theme.text(.subheadline)).opacity(0.8).lineLimit(2) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func progress(_ np: NowPlaying) -> some View {
        if let duration = np.duration, duration > 0 {
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                let pos = np.position(at: ctx.date, fetched: fetched) ?? 0
                VStack(spacing: 4) {
                    ProgressView(value: min(pos, duration), total: duration).tint(.white)
                    HStack {
                        Text(trackTime(pos))
                        Spacer()
                        Text("-" + trackTime(duration - pos))
                    }
                    .font(Theme.text(.caption, .bold)).monospacedDigit().opacity(0.7)
                }
            }
        }
    }

    private func controls(_ np: NowPlaying) -> some View {
        HStack(spacing: compact ? 18 : 26) {
            if np.supports?.shuffle == true {
                button("shuffle", on: np.shuffle == true) { await act("shuffle_set", np.shuffle != true) }
            }
            button("backward.fill", enabled: np.supports?.previous ?? true) { await act("previous") }
            Button { Task { await act("play_pause") } } label: {
                Image(systemName: np.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 28, weight: .bold))
                    .frame(width: 64, height: 64)
                    .background(.white, in: Circle())
                    .foregroundStyle(Color(hex: "#23263A"))
            }
            .accessibilityLabel(np.isPlaying ? "Pause" : "Play")
            button("forward.fill", enabled: np.supports?.next ?? true) { await act("next") }
            if np.supports?.repeat == true {
                let mode = np.repeat ?? "off"
                button(mode == "one" ? "repeat.1" : "repeat", on: mode != "off") {
                    await act("repeat_set", mode == "off" ? "all" : mode == "all" ? "one" : "off")
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func button(_ symbol: String, enabled: Bool = true, on: Bool? = nil, _ run: @escaping () async -> Void) -> some View {
        Button { Task { await run() } } label: {
            Image(systemName: symbol)
                .font(.system(size: on == nil ? 24 : 18, weight: .bold))
                .frame(width: 46, height: 46)
                .background(on == true ? Color.white.opacity(0.18) : .clear, in: Circle())
                .opacity(on == false ? 0.6 : 1)
        }
        .disabled(!enabled)
        .accessibilityLabel(symbol)
    }

    private func volumeRow(_ v: Double, muted: Bool) -> some View {
        HStack(spacing: 10) {
            Button { Task { await act("volume_mute", !muted) } } label: {
                Image(systemName: muted || v == 0 ? "speaker.slash.fill" : "speaker.wave.2.fill").frame(width: 30)
            }
            .accessibilityLabel(muted ? "Unmute" : "Mute")
            Slider(value: Binding(get: { volume ?? (muted ? 0 : v) }, set: { x in
                volume = x
                // At most a few updates a second while dragging; the last one always goes.
                if Date().timeIntervalSince(sent) > 0.25 { sent = Date(); Task { await act("volume_set", x) } }
            }), in: 0...1) { editing in
                if !editing, let x = volume { Task { await act("volume_set", x) } }
            }
            .tint(.white)
            .accessibilityLabel("Volume")
        }
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

private struct QueuePane: View {
    @Environment(AppModel.self) private var model
    let onLibrary: () -> Void
    @State private var queue: MediaQueue?
    @State private var failed: String?
    @State private var picked: QueueTrack?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let q = queue {
                if q.items.isEmpty {
                    VStack(spacing: 12) {
                        Text("The queue is empty").font(Theme.text(.headline, .heavy))
                        Button("Find something to play", action: onLibrary).buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 30)
                } else {
                    if let cur = q.items.first(where: \.current) {
                        heading("Now playing")
                        TrackRow(title: cur.title, detail: cur.detail, thumb: cur.thumb, trailing: nil, current: true)
                    }
                    let next = q.items.filter { !$0.current }
                    if !next.isEmpty { heading("Up next") }
                    ForEach(next) { t in
                        Button { if q.can_jump || q.can_remove || q.can_move { picked = t } } label: {
                            TrackRow(title: t.title, detail: t.detail, thumb: t.thumb, trailing: trackTime(t.duration), current: false)
                        }
                        .buttonStyle(.plain)
                    }
                    if !q.full && q.source == "music_assistant" {
                        Text("Home Assistant only says what's on now and next. Connect Music Assistant in Settings › Music on a wall screen to see and change the whole queue.")
                            .font(Theme.text(.footnote)).foregroundStyle(Theme.muted).padding(.top, 8)
                    }
                }
            } else if let failed {
                Text(failed).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            } else {
                ProgressView().frame(maxWidth: .infinity).padding(30)
            }
        }
        .confirmationDialog(picked?.title ?? "", isPresented: Binding(get: { picked != nil }, set: { if !$0 { picked = nil } }), titleVisibility: .visible) {
            if let t = picked, let q = queue {
                if q.can_jump { Button("Play now") { act(t, "play") } }
                if q.can_move { Button("Play next") { act(t, "next") } }
                if q.can_remove { Button("Remove from queue", role: .destructive) { act(t, "remove") } }
            }
        }
        .task(id: model.rev("media")) { await load() }
    }

    private func heading(_ text: String) -> some View {
        Text(text.uppercased()).font(Theme.text(.caption, .heavy)).tracking(0.8).foregroundStyle(Theme.muted).padding(.top, 8)
    }

    private func load() async {
        do {
            guard let api = model.api else { return }
            queue = try await api.mediaQueue()
            failed = nil
        } catch {
            failed = error.localizedDescription
        }
    }

    private func act(_ t: QueueTrack, _ action: String) {
        Task {
            _ = await model.call { try await $0.queueAction(action, key: t.key) }
            await load()
        }
    }
}

struct TrackRow: View {
    let title: String
    let detail: String?
    let thumb: String?
    let trailing: String?
    let current: Bool

    var body: some View {
        HStack(spacing: 12) {
            Thumb(path: thumb).frame(width: 48, height: 48)
            VStack(alignment: .leading, spacing: 2) {
                Text(title.isEmpty ? "Unknown track" : title).font(Theme.text(.body, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                if let detail { Text(detail).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted).lineLimit(1) }
            }
            Spacer(minLength: 0)
            if current {
                Image(systemName: "waveform").foregroundStyle(Theme.accent).symbolEffect(.variableColor.iterative)
            } else if let trailing, !trailing.isEmpty {
                Text(trailing).font(Theme.text(.subheadline)).monospacedDigit().foregroundStyle(Theme.muted)
            }
        }
        .padding(8)
        .background(current ? Theme.accent.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(Rectangle())
    }
}

struct Thumb: View {
    let path: String?
    var round = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: "#3A3F62"), Color(hex: "#5A4F82")], startPoint: .topLeading, endPoint: .bottomTrailing)
            Image(systemName: "music.note").foregroundStyle(.white.opacity(0.7))
            RemoteImage(path: path)
        }
        .clipShape(round ? AnyShape(Circle()) : AnyShape(RoundedRectangle(cornerRadius: 8, style: .continuous)))
    }
}

// MARK: Library

private let firstSections = ["albums", "playlists", "podcasts", "radio", "artists", "audiobooks", "tracks"]

private struct LibraryPane: View {
    @Environment(AppModel.self) private var model
    let musicAssistant: Bool
    @State private var sections: [MediaItem] = []
    @State private var section: MediaItem?
    @State private var page: MediaBrowse?
    @State private var failed: String?
    @State private var query = ""
    @State private var found: [MediaItem]?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if musicAssistant {
                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(Theme.muted)
                    TextField("Search albums, artists, playlists, podcasts", text: $query)
                        .submitLabel(.search)
                        .autocorrectionDisabled()
                    if !query.isEmpty {
                        Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.muted) }
                    }
                }
                .padding(10)
                .background(Theme.surface2, in: Capsule())
            }
            if found == nil && sections.count > 1 {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(sections, id: \.id) { s in
                            Button(s.title) { section = s }
                                .font(Theme.text(.subheadline, .heavy))
                                .padding(.horizontal, 14).padding(.vertical, 8)
                                .background(section?.id == s.id ? Theme.accent : Theme.surface2, in: Capsule())
                                .foregroundStyle(section?.id == s.id ? .white : Theme.text)
                        }
                    }
                }
            }
            if let failed {
                Text(failed).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            } else if let found {
                if found.isEmpty { Text("Nothing found.").foregroundStyle(Theme.muted) }
                LibraryItems(items: found)
            } else if let page, page.id == section?.id {
                if page.items.isEmpty { Text("Nothing here yet.").foregroundStyle(Theme.muted) }
                LibraryItems(items: page.items)
            } else {
                ProgressView().frame(maxWidth: .infinity).padding(30)
            }
        }
        .task { await loadTop() }
        .task(id: section?.id) {
            guard let section else { return }
            page = await model.call { try await $0.browse(section) }
        }
        .task(id: query) {
            let text = query.trimmingCharacters(in: .whitespaces)
            guard !text.isEmpty else { found = nil; return }
            try? await Task.sleep(for: .milliseconds(450))
            guard !Task.isCancelled else { return }
            found = await model.call { try await $0.searchMusic(text) } ?? []
        }
    }

    private func loadTop() async {
        guard sections.isEmpty, let api = model.api else { return }
        do {
            var top = try await api.browse(nil)
            // A single folder (a Sonos speaker's Favourites) is opened straight away.
            if top.items.count == 1, top.items[0].can_expand { top = try await api.browse(top.items[0]) }
            let rank = { (i: MediaItem) in firstSections.firstIndex(of: i.id) ?? 99 }
            sections = top.items.filter(\.can_expand).sorted { rank($0) < rank($1) }
            section = sections.first
            failed = nil
        } catch {
            failed = error.localizedDescription
        }
    }
}

/// Tiles for albums, playlists, podcasts...; rows for tracks and episodes. Opening a folder pushes it.
struct LibraryItems: View {
    let items: [MediaItem]
    @State private var picked: MediaItem?

    var body: some View {
        let tiles = items.filter(\.isTile)
        let rows = items.filter { !$0.isTile }
        VStack(alignment: .leading, spacing: 10) {
            if !tiles.isEmpty {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 12)], spacing: 14) {
                    ForEach(Array(tiles.enumerated()), id: \.offset) { _, item in
                        tile(item)
                    }
                }
            }
            ForEach(Array(rows.enumerated()), id: \.offset) { _, item in
                Button { picked = item } label: {
                    TrackRow(title: item.title, detail: item.subtitle, thumb: item.thumb, trailing: nil, current: false)
                }
                .buttonStyle(.plain)
                .disabled(!item.can_play)
            }
        }
        .modifier(PlayChoices(item: $picked))
    }

    @ViewBuilder
    private func tile(_ item: MediaItem) -> some View {
        let label = VStack(alignment: .leading, spacing: 4) {
            Thumb(path: item.thumb, round: item.kind == "artist").aspectRatio(1, contentMode: .fit)
            Text(item.title).font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.text).lineLimit(2)
            if let sub = item.subtitle { Text(sub).font(Theme.text(.caption)).foregroundStyle(Theme.muted).lineLimit(1) }
        }
        Group {
            if item.can_expand {
                NavigationLink(value: item) { label }
            } else {
                Button { picked = item } label: { label }
            }
        }
        .buttonStyle(.plain)
        .contextMenu {
            if item.can_play { PlayButtons(item: item) }
        }
    }
}

/// Play now / Play next / Add to queue, as a dialog for the picked item.
private struct PlayChoices: ViewModifier {
    @Binding var item: MediaItem?

    func body(content: Content) -> some View {
        content.confirmationDialog(item?.title ?? "", isPresented: Binding(get: { item != nil }, set: { if !$0 { item = nil } }),
                                   titleVisibility: .visible) {
            if let item { PlayButtons(item: item) }
        }
    }
}

private struct PlayButtons: View {
    @Environment(AppModel.self) private var model
    let item: MediaItem

    var body: some View {
        Button("Play now", systemImage: "play.fill") { play("replace") }
        Button("Play next", systemImage: "text.line.first.and.arrowtriangle.forward") { play("next") }
        Button("Add to queue", systemImage: "text.badge.plus") { play("add") }
    }

    private func play(_ enqueue: String) {
        Task {
            _ = await model.call { try await $0.play(item, enqueue: enqueue) }
            model.bump("media")
        }
    }
}

/// An album, playlist, podcast or artist: its picture, Play / Next / Queue, and what's in it.
private struct LibraryFolder: View {
    @Environment(AppModel.self) private var model
    let folder: MediaItem
    @State private var page: MediaBrowse?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 14) {
                    Thumb(path: page?.thumb ?? folder.thumb, round: folder.kind == "artist").frame(width: 110, height: 110)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(folder.title).font(Theme.text(.title2, .heavy)).foregroundStyle(Theme.text).lineLimit(3)
                        if let sub = page?.subtitle ?? folder.subtitle { Text(sub).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted) }
                    }
                }
                if page?.can_play ?? folder.can_play {
                    HStack(spacing: 10) {
                        PlayButtons(item: page?.item ?? folder)
                    }
                    .buttonStyle(.bordered)
                    .labelStyle(.iconOnly)
                    .controlSize(.large)
                }
                if let page {
                    if page.items.isEmpty { Text("Nothing here yet.").foregroundStyle(Theme.muted) }
                    LibraryItems(items: page.items)
                } else {
                    ProgressView().frame(maxWidth: .infinity).padding(30)
                }
            }
            .padding(16)
            .frame(maxWidth: 1000)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.bg.ignoresSafeArea())
        .navigationTitle(folder.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { page = await model.call { try await $0.browse(folder) } }
    }
}

// MARK: Rooms

private struct RoomsPane: View {
    @Environment(AppModel.self) private var model
    @State private var rooms: MediaRooms?
    @State private var failed: String?
    @State private var busy: String?

    var body: some View {
        VStack(spacing: 10) {
            if let r = rooms {
                if !r.can_group {
                    Text("This speaker can't play in a group from Moonlight. Each room's volume still works.")
                        .font(Theme.text(.footnote)).foregroundStyle(Theme.muted)
                }
                ForEach(r.rooms) { room in
                    RoomRow(room: room, canGroup: r.can_group, busy: busy == room.entity_id) { action, value in
                        await act(room.entity_id, action, value)
                    }
                }
            } else if let failed {
                Text(failed).font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            } else {
                ProgressView().frame(maxWidth: .infinity).padding(30)
            }
        }
        .task(id: model.rev("media")) { await load() }
    }

    private func load() async {
        do {
            guard let api = model.api else { return }
            rooms = try await api.rooms()
            failed = nil
        } catch {
            failed = error.localizedDescription
        }
    }

    private func act(_ room: String, _ action: String, _ value: Any?) async {
        if action == "join" || action == "unjoin" { busy = room }
        if let r = await model.call({ try await $0.roomAction(room, action, value: value) }) { rooms = r }
        busy = nil
    }
}

private struct RoomRow: View {
    let room: MediaRoom
    let canGroup: Bool
    let busy: Bool
    let act: (String, Any?) async -> Void
    @State private var volume: Double?
    @State private var sent = Date.distantPast

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(room.name).font(Theme.text(.body, .heavy)).foregroundStyle(Theme.text)
                    Text(room.this ? "This speaker" : room.playing.map { "Playing \($0)" } ?? (room.grouped ? "In this group" : "Not playing"))
                        .font(Theme.text(.footnote)).foregroundStyle(Theme.muted).lineLimit(1)
                }
                Spacer()
                if !room.this && canGroup {
                    Button {
                        Task { await act(room.grouped ? "unjoin" : "join", nil) }
                    } label: {
                        Label(room.grouped ? "In group" : "Add", systemImage: room.grouped ? "checkmark" : "plus")
                            .font(Theme.text(.subheadline, .heavy))
                    }
                    .buttonStyle(.bordered)
                    .tint(room.grouped ? Theme.accent : Theme.muted)
                    .disabled(busy)
                }
            }
            if room.can_volume, let v = room.volume {
                HStack {
                    Button { Task { await act("mute", !(room.muted ?? false)) } } label: {
                        Image(systemName: room.muted == true || v == 0 ? "speaker.slash.fill" : "speaker.wave.2.fill").frame(width: 28)
                    }
                    .foregroundStyle(Theme.muted)
                    Slider(value: Binding(get: { volume ?? (room.muted == true ? 0 : v) }, set: { x in
                        volume = x
                        if Date().timeIntervalSince(sent) > 0.25 { sent = Date(); Task { await act("volume", x) } }
                    }), in: 0...1) { editing in
                        if !editing, let x = volume { Task { await act("volume", x); volume = nil } }
                    }
                    .accessibilityLabel("\(room.name) volume")
                }
            }
        }
        .padding(12)
        .background(room.grouped ? Theme.accent.opacity(0.12) : Theme.surface2, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
