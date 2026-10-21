import SwiftUI
import UIKit

/// The family's photos (from Immich, via Moonlight) as a full-screen slideshow with the clock, like the screensaver
/// on the wall screens: everything shuffled, or one album from start to finish.
struct PhotosView: View {
    @Environment(AppModel.self) private var model
    @State private var photos: [Photo] = []
    @State private var albums: [PhotoAlbum] = []
    @State private var playing = false
    @State private var order: [Photo] = []
    /// The album the remote is on: the picture on the right shows its first photo.
    @State private var focused: PhotoAlbum?

    var body: some View {
        Screen {
            HStack(alignment: .top, spacing: 50) {
                VStack(alignment: .leading, spacing: 24) {
                    Text(photos.isEmpty
                         ? "Connect Immich in Moonlight Settings › Screensaver photos to show your family's albums here."
                         : "\(photos.count) photos from your albums, with the time and what's playing.")
                        .font(Theme.font(28, .bold)).foregroundStyle(Theme.muted)
                    Button { play(photos.shuffled()) } label: { Label("Play all", systemImage: "shuffle") }
                        .buttonStyle(.pillProminent)
                        .disabled(photos.isEmpty)
                    if !albums.isEmpty {
                        Text("ALBUMS").font(Theme.font(20, .heavy)).tracking(1).foregroundStyle(Theme.muted)
                            .padding(.top, 8)
                        ScrollView {
                            VStack(spacing: 14) {
                                ForEach(albums) { albumButton($0) }
                            }
                            .padding(14)
                        }
                        .scrollClipDisabled()
                        .padding(-14)
                        .focusSection()
                    }
                }
                .frame(width: 560, alignment: .leading)
                // The photo fills the space it's given; on its own a filled image grows to its own shape and pushes
                // the whole page (header included) off the screen.
                Color.clear
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .overlay { RemoteImage(path: preview?.url) }
                    .background(Theme.logoGradient.opacity(0.35))
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                    .padding(.bottom, 50)
            }
        }
        .task(id: model.rev("photos")) {
            if let v = await model.call({ try await $0.photos() }) {
                photos = v.photos
                let ids = Set(v.photos.map(\.id))
                albums = (v.albums ?? []).filter { $0.photos.contains(where: ids.contains) }
            }
        }
        .fullScreenCover(isPresented: $playing) {
            Slideshow(photos: order, seconds: Double(model.settings?.screensaver_seconds ?? 10))
        }
    }

    private var preview: Photo? {
        guard let first = focused?.photos.first else { return photos.first }
        return photos.first { $0.id == first } ?? photos.first
    }

    private func play(_ list: [Photo]) {
        guard !list.isEmpty else { return }
        order = list
        playing = true
    }

    /// An album plays from its oldest photo to its newest.
    private func albumButton(_ album: PhotoAlbum) -> some View {
        Button {
            let byId = Dictionary(photos.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
            play(album.photos.compactMap { byId[$0] })
        } label: {
            HStack(spacing: 16) {
                Image(systemName: album.id == "favorites" ? "heart.fill" : album.id == "on-this-day" ? "calendar" : "photo.stack")
                    .font(.system(size: 26, weight: .semibold)).foregroundStyle(Theme.accent).frame(width: 36)
                Text(album.name).font(Theme.font(28, .heavy)).foregroundStyle(Theme.text).lineLimit(1)
                Spacer()
                Text("\(album.photos.count)").font(Theme.font(24, .heavy)).foregroundStyle(Theme.muted)
            }
            .padding(.horizontal, 22).padding(.vertical, 18)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .buttonStyle(.moonCard(radius: 18))
        .onFocusChange { if $0 { focused = album } }
    }
}

struct Slideshow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let photos: [Photo]
    let seconds: Double
    @State private var index = 0
    @State private var paused = false
    @State private var zoom = false
    @State private var slide: Slide?
    /// Photos already shown beside another one, so they don't come round again on their own straight after.
    @State private var paired: Set<String> = []

    /// What's on screen: one photo, or two portrait ones from the same day side by side.
    struct Slide: Equatable {
        let index: Int
        let main: UIImage
        var second: UIImage?
        var secondId: String?
    }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Color.black.ignoresSafeArea()
            if let slide {
                ZStack {
                    // The photo again, blurred and dimmed, filling the bars beside it.
                    Color.clear
                        .overlay { Image(uiImage: slide.main).resizable().aspectRatio(contentMode: .fill) }
                        .clipped()
                        .blur(radius: 50)
                        .overlay(Color.black.opacity(0.35))
                    HStack(spacing: 24) {
                        Image(uiImage: slide.main).resizable().aspectRatio(contentMode: .fit)
                        if let second = slide.second {
                            Image(uiImage: second).resizable().aspectRatio(contentMode: .fit)
                        }
                    }
                    .shadow(color: .black.opacity(0.45), radius: 30)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .scaleEffect(zoom ? 1.06 : 1)
                }
                .ignoresSafeArea()
                .id(slide.index)
                .transition(.opacity)
            }
            TimelineView(.everyMinute) { ctx in
                VStack(alignment: .leading, spacing: 4) {
                    // Weather on top, then the clock and date, as on the screens' photo screensaver.
                    if let w = model.weather {
                        HStack(spacing: 12) {
                            WeatherGlyph(condition: w.current.condition, size: 44)
                            Text("\(w.current.temp)°").font(Theme.font(44, .heavy))
                            if let d = w.day(model.dates.today) {
                                Text("\(d.high)° / \(d.low)°").font(Theme.font(30, .bold)).opacity(0.9)
                            }
                        }
                        .padding(.bottom, 6)
                    }
                    Text(model.dates.clock(ctx.date)).font(Theme.font(96, .heavy))
                    Text(model.dates.longDate(ctx.date)).font(Theme.font(34, .bold)).opacity(0.85)
                }
                .foregroundStyle(.white)
                .shadow(color: .black.opacity(0.5), radius: 16)
                .padding(70)
            }
            if model.settings?.photo_details != false, !photos.isEmpty {
                let photo = photos[index % photos.count]
                let place = (photo.place?.isEmpty == false) ? photo.place : nil
                if photo.takenText != nil || place != nil {
                    // When and where it was taken, the place underneath, and a camera so it reads as the photo's details.
                    HStack(spacing: 14) {
                        VStack(alignment: .trailing, spacing: 2) {
                            if let when = photo.takenText { Text(when).font(Theme.font(24, .bold)) }
                            if let place { Text(place).font(Theme.font(22, .semibold)).opacity(0.9) }
                        }
                        Image(systemName: "camera").font(.system(size: 28, weight: .semibold))
                    }
                    .foregroundStyle(.white.opacity(0.85))
                    .shadow(color: .black.opacity(0.6), radius: 10)
                    .padding(.top, 50).padding(.trailing, 70)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                    .id("caption\(index)")
                    .transition(.opacity)
                }
            }
            if paused {
                Image(systemName: "pause.fill").font(.system(size: 60)).foregroundStyle(.white.opacity(0.8))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .focusable()
        .onPlayPauseCommand { paused.toggle() }
        .onMoveCommand { dir in
            if dir == .right { advance(1) }
            if dir == .left { advance(-1) }
        }
        .onExitCommand { dismiss() }
        .task(id: "\(index)|\(paused)") {
            if slide?.index != index, let next = await load(index) {
                withAnimation(.easeInOut(duration: 1.2)) { slide = next }
                if let id = next.secondId { paired.insert(id) }
            }
            zoom = false
            withAnimation(.linear(duration: seconds)) { zoom = true }
            guard !paused else { return }
            try? await Task.sleep(for: .seconds(seconds))
            if !Task.isCancelled { advance(1) }
        }
        // Keep the slideshow up instead of the Apple TV's own screensaver while it's playing.
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }

    private func advance(_ step: Int) {
        guard !photos.isEmpty else { return }
        if paired.count >= photos.count - 1 { paired = [] }
        var next = (index + step + photos.count) % photos.count
        // Skip photos already shown as the second of a pair.
        for _ in 0..<photos.count where paired.contains(photos[next].id) {
            next = (next + step + photos.count) % photos.count
        }
        index = next
    }

    /// The photo at `i`; if it's portrait, with another portrait one taken the same day at a different time.
    private func load(_ i: Int) async -> Slide? {
        guard let api = model.api, !photos.isEmpty else { return nil }
        let photo = photos[i % photos.count]
        guard let main = await image(photo, api) else { return nil }
        var out = Slide(index: i, main: main)
        guard isPortrait(main), let day = photo.taken_at?.prefix(10), day.count == 10 else { return out }
        let candidates = photos.filter {
            $0.id != photo.id && !paired.contains($0.id) && $0.taken_at?.prefix(10) == day && $0.taken_at != photo.taken_at
        }
        // Closest in time first; landscape ones are passed over.
        for other in candidates.sorted(by: { gap($0, photo) < gap($1, photo) }).prefix(6) {
            if let img = await image(other, api), isPortrait(img) {
                out.second = img
                out.secondId = other.id
                break
            }
        }
        return out
    }

    private func image(_ photo: Photo, _ api: APIClient) async -> UIImage? {
        guard let url = api.resolve(photo.url) else { return nil }
        return await ImageCache.shared.image(url, api: api)
    }

    /// From the picture itself (Immich's own size can be before the camera's rotation).
    private func isPortrait(_ img: UIImage) -> Bool { img.size.height > img.size.width * 1.05 }

    /// Minutes apart, from the taken_at digits (HH:mm after the date).
    private func gap(_ a: Photo, _ b: Photo) -> Int {
        func minutes(_ p: Photo) -> Int {
            guard let t = p.taken_at, t.count >= 16 else { return 0 }
            let hm = t.dropFirst(11).prefix(5).split(separator: ":").compactMap { Int($0) }
            return hm.count == 2 ? hm[0] * 60 + hm[1] : 0
        }
        return abs(minutes(a) - minutes(b))
    }
}
