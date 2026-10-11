import SwiftUI
import UIKit

/// The family's photos (from Immich, via Moonlight) as a full-screen slideshow with the clock, like the screensaver
/// on the wall screens.
struct PhotosView: View {
    @Environment(AppModel.self) private var model
    @State private var photos: [Photo] = []
    @State private var playing = false
    @State private var order: [Photo] = []

    var body: some View {
        Screen {
            HStack(alignment: .top, spacing: 50) {
                VStack(alignment: .leading, spacing: 24) {
                    Text("Photos").font(Theme.font(48, .heavy)).foregroundStyle(Theme.text)
                    Text(photos.isEmpty
                         ? "Connect Immich in Moonlight Settings › Screensaver photos to show your family's albums here."
                         : "\(photos.count) photos from your albums, with the time and what's playing.")
                        .font(Theme.font(28, .bold)).foregroundStyle(Theme.muted)
                    Button { order = photos.shuffled(); playing = true } label: { Label("Play slideshow", systemImage: "play.fill") }
                        .buttonStyle(.pillProminent)
                        .disabled(photos.isEmpty)
                }
                .frame(width: 560, alignment: .leading)
                RemoteImage(path: photos.first?.url)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Theme.logoGradient.opacity(0.35))
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                    .padding(.bottom, 50)
            }
        }
        .task(id: model.rev("photos")) {
            if let v = await model.call({ try await $0.photos() }) { photos = v.photos }
        }
        .fullScreenCover(isPresented: $playing) {
            Slideshow(photos: order, seconds: Double(model.settings?.screensaver_seconds ?? 10))
        }
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

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Color.black.ignoresSafeArea()
            if !photos.isEmpty {
                RemoteImage(path: photos[index % photos.count].url, contentMode: .fit)
                    .scaleEffect(zoom ? 1.06 : 1)
                    .id(index)
                    .transition(.opacity)
                    .ignoresSafeArea()
            }
            TimelineView(.everyMinute) { ctx in
                VStack(alignment: .leading, spacing: 4) {
                    Text(model.dates.clock(ctx.date)).font(Theme.font(96, .heavy))
                    Text(model.dates.longDate(ctx.date)).font(Theme.font(34, .bold)).opacity(0.85)
                }
                .foregroundStyle(.white)
                .shadow(color: .black.opacity(0.5), radius: 16)
                .padding(70)
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
        withAnimation(.easeInOut(duration: 1.2)) { index = (index + step + photos.count) % photos.count }
    }
}
