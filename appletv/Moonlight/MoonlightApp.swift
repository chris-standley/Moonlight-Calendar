import SwiftUI

@main
struct MoonlightApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task { await model.start() }
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.phase {
            case .starting:
                VStack(spacing: 30) {
                    LogoMark(size: 160)
                    ProgressView()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Theme.bg.ignoresSafeArea())
            case .setup:
                SetupView()
            case .ready:
                MainTabs()
            }
        }
        .animation(.easeInOut(duration: 0.35), value: model.phase)
    }
}

struct MainTabs: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TabView {
            Tab("Today", systemImage: "sun.horizon") { TodayView() }
            Tab("Calendar", systemImage: "calendar") { CalendarView() }
            Tab("Chores", systemImage: "checkmark.circle") { ChoresView() }
            Tab("Rewards", systemImage: "star") { RewardsView() }
            Tab("Meals", systemImage: "fork.knife") { MealsView() }
            Tab("Lists", systemImage: "list.bullet") { ListsView() }
            Tab("Photos", systemImage: "photo.on.rectangle") { PhotosView() }
            Tab("Settings", systemImage: "gearshape") { SettingsView() }
        }
        .task { await model.refreshWeatherPeriodically() }
        // The remote's Play/Pause controls this screen's speaker from anywhere (Photos uses it for the slideshow).
        .onPlayPauseCommand {
            Task {
                _ = await model.call { try await $0.media("play_pause") }
                model.bump("media")
            }
        }
    }
}

/// The crescent mark from the wall screens' rail.
struct LogoMark: View {
    var size: CGFloat = 80

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.28, style: .continuous).fill(Theme.logoGradient)
            Canvas { ctx, sz in
                let s = sz.width / 32
                // Crescent: a disc with an offset disc cut out (path from the web logo, M19.5 7.5a9 9 0 100 17 7.2 7.2 0 010-17z).
                var moon = Path(ellipseIn: CGRect(x: 6.5 * s, y: 7.5 * s, width: 17 * s, height: 17 * s))
                moon = moon.subtracting(Path(ellipseIn: CGRect(x: 12.3 * s, y: 7.5 * s, width: 14.4 * s, height: 17 * s)))
                ctx.fill(moon, with: .color(.white))
                ctx.fill(Path(ellipseIn: CGRect(x: 21.7 * s, y: 8.7 * s, width: 2.6 * s, height: 2.6 * s)), with: .color(.white.opacity(0.85)))
                ctx.fill(Path(ellipseIn: CGRect(x: 24.6 * s, y: 14.1 * s, width: 1.8 * s, height: 1.8 * s)), with: .color(.white.opacity(0.7)))
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
