import AudioToolbox
import SwiftUI

/// Notifications and timers from Home Assistant (`/api/alerts`), as the wall screens show them: full screen ones
/// cover the app, toasts and small timers sit in the top corner. Dismissing one closes it on every screen; a full
/// screen one can also be put away on this device only (Menu on the Apple TV remote, or "Make small" for a timer).
struct ScreenAlertsOverlay: View {
    @Environment(AppModel.self) private var model
    @State private var alerts: [ScreenAlert] = []
    @State private var skew: Double = 0 // add-on clock minus this one, in ms
    @State private var small: Set<String> = []
    @State private var chimed: Set<String> = []
    @State private var cover: ScreenAlert?

    private var tv: Bool {
        #if os(tvOS)
        true
        #else
        false
        #endif
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let t = context.date.timeIntervalSince1970 * 1000 + skew
            let live = alerts.filter { ($0.expires_at ?? .infinity) > t }
            let corner = Array(live.filter { !$0.isFull(at: t) || small.contains($0.key) }.reversed().prefix(3))
            VStack(alignment: .trailing, spacing: tv ? 20 : 10) {
                ForEach(corner) { a in
                    AlertCard(alert: a, now: t, tv: tv) { dismiss(a) }
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            .frame(maxWidth: tv ? 640 : 420)
            .padding(.top, tv ? 50 : 8)
            .padding(.trailing, tv ? Theme.gutter : 12)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            .animation(.easeInOut(duration: 0.3), value: corner.map(\.key))
            .onChange(of: Int(t / 1000)) { chime(live, t) }
            .onChange(of: live.last { $0.isFull(at: t) && !small.contains($0.key) }?.key) { _, _ in
                cover = live.last { $0.isFull(at: t) && !small.contains($0.key) }
            }
        }
        .fullScreenCover(item: $cover, onDismiss: {}) { a in
            FullScreenAlert(alert: a, skew: skew, tv: tv,
                            dismiss: { dismiss(a) }, putAway: { small.insert(a.key); cover = nil })
                .environment(model)
        }
        .task(id: model.rev("alerts")) { await load() }
        .task {
            // In case a push was missed.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                await load()
            }
        }
    }

    private func load() async {
        guard let now = await model.call({ try await $0.alerts() }) else { return }
        skew = now.server_time - Date().timeIntervalSince1970 * 1000
        alerts = now.alerts
        let t = now.server_time
        let top = alerts.last { $0.isFull(at: t) && !small.contains($0.key) && ($0.expires_at ?? .infinity) > t }
        if top?.key != cover?.key { cover = top }
        chime(alerts, t)
    }

    private func dismiss(_ a: ScreenAlert) {
        alerts.removeAll { $0.id == a.id }
        if cover?.id == a.id { cover = nil }
        Task {
            _ = await model.call { try await $0.dismissAlert(a.id) }
            await load()
        }
    }

    /// A chime for a new notification that asks for one, and for a timer reaching zero (not for old ones on launch).
    private func chime(_ live: [ScreenAlert], _ t: Double) {
        for a in live where a.chime && !chimed.contains(a.key) {
            let at = a.isTimer && !a.countsUp ? (a.ends_at ?? 0) : a.created_at
            guard at <= t else { continue }
            chimed.insert(a.key)
            if t - at < 30_000 {
                #if os(iOS)
                AudioServicesPlayAlertSound(SystemSoundID(1005))
                #endif
            }
        }
    }
}

/// Time left: 4:05, 1:02:03, or for a countdown to a day "3 days 4 hr".
func timeLeft(_ ms: Double) -> String {
    let s = max(0, Int((ms / 1000).rounded(.up)))
    if s >= 86_400 {
        let d = s / 86_400, h = (s % 86_400) / 3600
        return "\(d) \(d == 1 ? "day" : "days")" + (h > 0 ? " \(h) hr" : "")
    }
    let h = s / 3600, m = (s % 3600) / 60, r = s % 60
    return h > 0 ? String(format: "%d:%02d:%02d", h, m, r) : String(format: "%d:%02d", m, r)
}

/// Time gone on a timer counting up, the same way: 0:00 at the start, then 4:05.
func timeSince(_ ms: Double) -> String {
    timeLeft((max(0, ms) / 1000).rounded(.down) * 1000)
}

/// "since 10:41" for a timer counting up.
func sinceText(_ alert: ScreenAlert) -> String {
    let at = Date(timeIntervalSince1970: (alert.started_at ?? alert.created_at) / 1000)
    return "since " + at.formatted(date: .omitted, time: .shortened)
}

/// The big number on a timer.
func timerText(_ alert: ScreenAlert, _ t: Double) -> String {
    if alert.isDone(t) { return "Time's up" }
    return alert.countsUp ? timeSince(t - (alert.started_at ?? t)) : timeLeft((alert.ends_at ?? 0) - t)
}

private struct AlertCard: View {
    let alert: ScreenAlert
    let now: Double
    let tv: Bool
    let dismiss: () -> Void
    @State private var drag: CGFloat = 0

    var body: some View {
        card
            .offset(x: drag)
            .opacity(1 - min(0.8, drag / 400))
        #if os(iOS)
            // Swipe right to dismiss (one that can be dismissed).
            .gesture(swipe, including: alert.dismissible ? .all : .subviews)
        #endif
    }

    #if os(iOS)
    private var swipe: some Gesture {
        DragGesture(minimumDistance: 12)
            .onChanged { drag = max(0, $0.translation.width) }
            .onEnded { value in
                if value.translation.width > 100 || value.predictedEndTranslation.width > 220 {
                    withAnimation(.easeOut(duration: 0.15)) { drag = 600 }
                    dismiss()
                } else {
                    withAnimation(.spring(duration: 0.25)) { drag = 0 }
                }
            }
    }
    #endif

    @ViewBuilder private var card: some View {
        let done = alert.isDone(now)
        let detail = alert.description?.isEmpty == false ? alert.description : alert.countsUp ? sinceText(alert) : nil
        HStack(spacing: tv ? 18 : 10) {
            if !alert.icon.isEmpty { Text(alert.icon).font(.system(size: tv ? 44 : 28)) }
            VStack(alignment: .leading, spacing: 2) {
                if alert.isTimer {
                    Text(timerText(alert, now))
                        .font(tv ? Theme.font(40, .heavy) : Theme.text(.title2, .heavy)).monospacedDigit()
                        .foregroundStyle(done ? Theme.starText : Theme.text)
                    Text([alert.label, detail].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · "))
                        .font(tv ? Theme.font(24, .semibold) : Theme.text(.footnote, .semibold))
                        .foregroundStyle(Theme.muted).lineLimit(1)
                } else {
                    if let title = alert.title, !title.isEmpty {
                        Text(title).font(tv ? Theme.font(30, .heavy) : Theme.text(.headline, .heavy))
                    }
                    if let message = alert.message, !message.isEmpty {
                        Text(message).font(tv ? Theme.font(24, .semibold) : Theme.text(.subheadline, .semibold))
                            .foregroundStyle(Theme.muted).lineLimit(3)
                    }
                }
            }
            Spacer(minLength: 0)
            // The TV can't focus the corner, so there it goes when its time is up or Home Assistant clears it.
            if alert.dismissible && !tv {
                Button(action: dismiss) {
                    Image(systemName: "xmark").font(.footnote.weight(.heavy)).frame(width: 32, height: 32)
                        .background(Theme.surface2, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(done || !alert.isTimer || alert.countsUp ? "Dismiss" : "Cancel timer")
            }
        }
        .padding(.vertical, tv ? 20 : 12)
        .padding(.horizontal, tv ? 26 : 14)
        .background(done ? Theme.starBg : Theme.surface, in: RoundedRectangle(cornerRadius: tv ? 28 : 18, style: .continuous))
        .shadow(color: .black.opacity(0.18), radius: tv ? 24 : 14, y: 6)
        .allowsHitTesting(!tv)
    }
}

private struct FullScreenAlert: View {
    let alert: ScreenAlert
    let skew: Double
    let tv: Bool
    let dismiss: () -> Void
    let putAway: () -> Void
    @State private var lift: CGFloat = 0

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let t = context.date.timeIntervalSince1970 * 1000 + skew
            VStack(spacing: tv ? 50 : 28) {
                Spacer(minLength: 0)
                if alert.isTimer { timer(t) } else { note }
                HStack(spacing: tv ? 40 : 14) {
                    if alert.isTimer {
                        Button("Make small", action: putAway)
                    }
                    if alert.dismissible {
                        Button(alert.isTimer && !alert.countsUp && !alert.isDone(t) ? "Cancel timer" : "Dismiss", action: dismiss)
                    }
                }
                .font(tv ? Theme.font(30) : Theme.text(.headline))
                #if os(iOS)
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                #endif
                Spacer(minLength: 0)
                #if os(iOS)
                VStack(spacing: 6) {
                    Capsule().fill(Theme.muted.opacity(0.5)).frame(width: 44, height: 5)
                    Text("Swipe up to make small").font(Theme.text(.footnote, .semibold)).foregroundStyle(Theme.muted)
                }
                #endif
            }
            .padding(tv ? 80 : 24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .multilineTextAlignment(.center)
            .offset(y: -lift)
            .background {
                ZStack {
                    Theme.bg
                    RadialGradient(colors: [Theme.accent.opacity(0.14), .clear], center: .init(x: 0.5, y: 0.35),
                                   startRadius: 0, endRadius: tv ? 900 : 500)
                }
                .ignoresSafeArea()
            }
        }
        #if os(tvOS)
        .onExitCommand(perform: putAway) // Menu puts it away on this TV only
        #else
        // Swipe up puts it away on this device only.
        .gesture(DragGesture(minimumDistance: 12)
            .onChanged { lift = max(0, -$0.translation.height) }
            .onEnded { value in
                if -value.translation.height > 120 || -value.predictedEndTranslation.height > 300 {
                    putAway()
                } else {
                    withAnimation(.spring(duration: 0.25)) { lift = 0 }
                }
            })
        #endif
        .interactiveDismissDisabled()
    }

    private var note: some View {
        VStack(spacing: tv ? 30 : 16) {
            if !alert.icon.isEmpty { Text(alert.icon).font(.system(size: tv ? 150 : 90)) }
            if let title = alert.title, !title.isEmpty {
                Text(title).font(tv ? Theme.font(80, .heavy) : Theme.text(.largeTitle, .heavy))
            }
            if let message = alert.message, !message.isEmpty {
                Text(message).font(tv ? Theme.font(40, .semibold) : Theme.text(.title3, .semibold)).foregroundStyle(Theme.muted)
            }
            if let image = alert.image {
                RemoteImage(path: image, contentMode: .fit)
                    .frame(maxWidth: tv ? 1100 : 500, maxHeight: tv ? 450 : 280)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            }
        }
    }

    private func timer(_ t: Double) -> some View {
        let done = alert.isDone(t)
        let start = alert.started_at ?? t
        // How much of the ring shows: a countdown fills towards zero; counting up, it fills towards when it goes
        // (and is full if it stays until dismissed).
        let fill: Double
        if alert.countsUp {
            fill = alert.expires_at.map { min(1, max(0, (t - start) / max(1, $0 - start))) } ?? 1
        } else {
            let ends = alert.ends_at ?? 0
            fill = done ? 1 : min(1, max(0, 1 - (ends - t) / max(1, ends - start)))
        }
        let size: CGFloat = tv ? 520 : 260
        return VStack(spacing: tv ? 30 : 14) {
            ZStack {
                Circle().stroke(Theme.surface2, lineWidth: tv ? 26 : 14)
                Circle()
                    .trim(from: 0, to: CGFloat(fill))
                    .stroke(done ? Theme.starText : Theme.accent, style: StrokeStyle(lineWidth: tv ? 26 : 14, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(.linear(duration: 1), value: Int(t / 1000))
                VStack(spacing: 6) {
                    if !alert.icon.isEmpty { Text(alert.icon).font(.system(size: tv ? 80 : 44)) }
                    Text(timerText(alert, t))
                        .font(.system(size: tv ? 110 : 54, weight: .heavy, design: .rounded)).monospacedDigit()
                        .foregroundStyle(done ? Theme.starText : Theme.text)
                        .minimumScaleFactor(0.5).lineLimit(1)
                        .padding(.horizontal, tv ? 50 : 24)
                    if alert.countsUp {
                        Text(sinceText(alert)).font(tv ? Theme.font(30, .semibold) : Theme.text(.headline, .semibold))
                            .foregroundStyle(Theme.muted)
                    }
                }
            }
            .frame(width: size, height: size)
            Text(alert.label ?? "").font(tv ? Theme.font(70, .heavy) : Theme.text(.largeTitle, .heavy))
            if let d = alert.description, !d.isEmpty {
                Text(d).font(tv ? Theme.font(36, .semibold) : Theme.text(.title3, .semibold)).foregroundStyle(Theme.muted)
            }
        }
    }
}
