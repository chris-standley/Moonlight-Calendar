import AVFoundation
import SwiftUI

/// When a camera sees a person, its live video pops up in the corner and goes 15 seconds after they've gone. Only when
/// it's turned on for the Apple TV in Settings › Security ("Pop up people on"; off by default, as the TV may already
/// show cameras from HomeKit). The TV plays the camera's full-resolution stream.
struct CameraPopUp: View {
    @Environment(AppModel.self) private var model
    @State private var shown: SecurityAlert?
    @State private var hide: Task<Void, Never>?

    private var enabled: Bool { model.settings?.security?.popup?["tv"] ?? false }

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            Color.clear
            if let shown, enabled {
                card(shown)
                    .padding(.trailing, Theme.gutter)
                    .padding(.bottom, 60)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .allowsHitTesting(false)
        .animation(.easeInOut(duration: 0.35), value: shown?.camera)
        .task(id: model.rev("security_alert", "settings")) { await load() }
        .task {
            // Belt and braces: an occasional check in case a push was missed.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await load()
            }
        }
    }

    private func load() async {
        guard enabled else { shown = nil; return }
        guard let alerts = await model.call({ try await $0.securityAlerts() }) else { return }
        if let first = alerts.first(where: { $0.camera == shown?.camera }) ?? alerts.first {
            hide?.cancel()
            hide = nil
            shown = first
        } else if shown != nil, hide == nil {
            hide = Task {
                try? await Task.sleep(for: .seconds(15))
                if !Task.isCancelled { shown = nil; hide = nil }
            }
        }
    }

    private func card(_ alert: SecurityAlert) -> some View {
        ZStack(alignment: .bottomLeading) {
            Color.black
            if let path = alert.video_hd_url ?? alert.video_url, let api = model.api, let url = api.resolve(path) {
                CameraVideo(url: url, token: api.token).id(alert.camera)
            } else {
                RemoteImage(path: alert.snapshot_url, contentMode: .fit)
            }
            HStack(spacing: 12) {
                Circle().fill(Theme.danger).frame(width: 14, height: 14)
                Text(alert.test ? "Test: \(alert.name)" : alert.name).font(Theme.font(24, .heavy)).foregroundStyle(.white)
            }
            .padding(.horizontal, 20).padding(.vertical, 12)
            .background(.black.opacity(0.55), in: Capsule())
            .padding(20)
        }
        .frame(width: 800, height: 450)
        .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).stroke(Theme.danger, lineWidth: 4))
        .shadow(color: .black.opacity(0.4), radius: 30, y: 10)
    }
}
