import SwiftUI

/// What's playing on this screen's speaker (Settings › Music). Hidden when nothing is set or playing.
/// The Siri Remote's Play/Pause button also controls it (see MainTabs).
struct NowPlayingCard: View {
    @Environment(AppModel.self) private var model
    @State private var np: NowPlaying?

    var body: some View {
        Group {
            if let np, np.configured, np.show {
                card(np)
            }
        }
        .task(id: model.rev("media", "settings")) { await load() }
        .task {
            // Belt and braces: an occasional refresh in case a push was missed.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await load()
            }
        }
    }

    private func load() async {
        if let v = await model.call({ try await $0.nowPlaying() }) { np = v }
    }

    private func act(_ action: String) {
        Task {
            if let v = await model.call({ try await $0.media(action) }) { np = v }
        }
    }

    private func card(_ np: NowPlaying) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 20) {
                RemoteImage(path: np.art_url)
                    .frame(width: 130, height: 130)
                    .background(Theme.surface2)
                    .overlay { if np.art_url == nil { Image(systemName: "music.note").font(.system(size: 50)).foregroundStyle(Theme.muted) } }
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                VStack(alignment: .leading, spacing: 6) {
                    Text(np.name ?? "Now playing").font(Theme.font(20, .heavy)).foregroundStyle(Theme.muted).lineLimit(1)
                    Text(np.title ?? "—").font(Theme.font(28, .heavy)).foregroundStyle(Theme.text).lineLimit(2)
                    if let artist = np.artist, !artist.isEmpty {
                        Text(artist).font(Theme.font(22, .bold)).foregroundStyle(Theme.muted).lineLimit(1)
                    }
                }
            }
            HStack(spacing: 24) {
                control("backward.fill", "previous", enabled: np.supports?.previous ?? true)
                control(np.isPlaying ? "pause.fill" : "play.fill", "play_pause", enabled: np.supports?.play_pause ?? true, big: true)
                control("forward.fill", "next", enabled: np.supports?.next ?? true)
            }
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .panel(padding: 26)
    }

    private func control(_ symbol: String, _ action: String, enabled: Bool, big: Bool = false) -> some View {
        Button { act(action) } label: {
            Image(systemName: symbol)
                .font(.system(size: big ? 34 : 26, weight: .bold))
                .frame(width: big ? 86 : 70, height: big ? 86 : 70)
        }
        .buttonStyle(.bordered)
        .clipShape(Circle())
        .disabled(!enabled)
        .accessibilityLabel(action == "play_pause" ? (np?.isPlaying == true ? "Pause" : "Play") : action.capitalized)
    }
}
