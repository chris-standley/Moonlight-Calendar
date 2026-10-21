import SwiftUI

/// Security on the TV: the alarm (arm it, or disarm it with its code, which goes straight to Home Assistant), its
/// sensors, and the cameras live. Select a camera to watch it full screen at full resolution.
struct SecurityView: View {
    @Environment(AppModel.self) private var model
    @State private var data: SecurityOverview?
    @State private var watching: SecurityOverview.Camera?
    /// Only play the tiles' video while this tab is showing.
    @State private var showing = false

    var body: some View {
        Screen {
            if data?.reachable == false {
                Text("Can't reach Home Assistant").font(Theme.font(26, .bold)).foregroundStyle(Theme.danger)
            }
            if let data, data.configured {
                HStack(alignment: .top, spacing: 36) {
                    VStack(spacing: 20) {
                        if let alarm = data.alarm { TVAlarmCard(alarm: alarm, reload: load) }
                        if !data.sensors.isEmpty {
                            ScrollView {
                                TVSensorList(sensors: data.sensors).padding(24)
                            }
                            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                        }
                    }
                    .frame(width: 620)
                    .focusSection()

                    ScrollView {
                        LazyVGrid(columns: [GridItem(.flexible(), spacing: 28), GridItem(.flexible(), spacing: 28)], spacing: 28) {
                            ForEach(data.cameras) { cam in
                                Button { watching = cam } label: {
                                    TVCameraTile(cam: cam, person: data.seesPerson(cam), live: showing && watching == nil)
                                }
                                .buttonStyle(.moonCard(radius: 22))
                            }
                        }
                        .padding(14)
                    }
                    .scrollClipDisabled()
                    .focusSection()
                }
                .padding(.bottom, 40)
            } else if data != nil {
                FamilyPrompt(text: "Security shows your alarm, its sensors and your cameras from Home Assistant. It needs Moonlight running as the Home Assistant add-on.")
            }
        }
        .onAppear { showing = true }
        .onDisappear { showing = false }
        .task(id: model.rev("security", "security_alert", "settings")) { await load() }
        .fullScreenCover(item: $watching) { TVCameraFull(cam: $0) }
    }

    private func load() async {
        if let d = await model.call({ try await $0.security() }) { data = d }
    }
}

/// The alarm: its state, who changed it and when, and buttons to arm it in each mode it offers or to disarm it.
/// Disarming asks for the alarm code; arming asks only if the panel needs one.
private struct TVAlarmCard: View {
    @Environment(AppModel.self) private var model
    let alarm: SecurityOverview.Alarm
    let reload: () async -> Void
    @State private var asking: String?
    @State private var code = ""
    @State private var message: String?
    @State private var busy = false

    private var color: Color {
        if !alarm.available { return Theme.muted }
        if alarm.state == "triggered" { return Theme.danger }
        if alarm.state == "disarmed" { return .green }
        return .orange
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 18) {
                Image(systemName: alarm.armed ? "lock.shield.fill" : alarm.state == "disarmed" ? "checkmark.shield" : "shield.lefthalf.filled")
                    .font(.system(size: 52, weight: .semibold))
                    .foregroundStyle(color)
                VStack(alignment: .leading, spacing: 4) {
                    Text(alarm.label).font(Theme.font(44, .heavy)).foregroundStyle(Theme.text)
                    if let when = SecurityOverview.ago(alarm.last_changed) {
                        Text(alarm.changed_by.map { "\(when) by \($0)" } ?? when)
                            .font(Theme.font(22, .bold)).foregroundStyle(Theme.muted)
                    }
                }
                Spacer(minLength: 0)
                if busy { ProgressView() }
            }
            if !alarm.open_sensors.isEmpty {
                Text("Open: \(alarm.open_sensors.joined(separator: ", "))")
                    .font(Theme.font(24, .heavy)).foregroundStyle(.orange)
            }
            if let message {
                Text(message).font(Theme.font(24, .heavy)).foregroundStyle(Theme.danger)
            }
            if alarm.available {
                if alarm.state == "disarmed" {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 240), spacing: 16)], alignment: .leading, spacing: 16) {
                        ForEach(alarm.modes, id: \.self) { mode in
                            Button(SecurityOverview.armLabel[mode] ?? "Arm \(mode)") { start(mode) }
                                .buttonStyle(.pill)
                        }
                    }
                } else {
                    Button("Disarm") { start("disarm") }.buttonStyle(.pillProminent)
                }
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .disabled(busy)
        .alert(asking == "disarm" ? "Disarm the alarm" : "Arm the alarm",
               isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } })) {
            SecureField("Alarm code", text: $code).keyboardType(.numberPad)
            Button("Cancel", role: .cancel) { code = "" }
            Button(asking == "disarm" ? "Disarm" : "Arm") {
                let action = asking ?? "disarm", entered = code
                code = ""
                Task { await send(action, entered) }
            }
        } message: {
            Text("Enter the alarm code. It goes straight to Home Assistant.")
        }
    }

    private func start(_ action: String) {
        if action == "disarm" || alarm.code_arm_required {
            asking = action
        } else {
            Task { await send(action, nil) }
        }
    }

    private func send(_ action: String, _ code: String?) async {
        guard let api = model.api else { return }
        busy = true
        do {
            try await api.setAlarm(action, code: code)
            message = nil
        } catch {
            message = error.localizedDescription
        }
        await reload()
        busy = false
    }
}

/// The sensors grouped like the wall screens: doors, windows, motion, smoke and leaks.
private struct TVSensorList: View {
    let sensors: [SecurityOverview.Sensor]

    private static let groups = [("doors", "Doors"), ("windows", "Windows"), ("motion", "Motion"),
                                 ("environment", "Smoke and leaks"), ("other", "Other")]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Self.groups, id: \.0) { group in
                let rows = sensors.filter { $0.group == group.0 }
                if !rows.isEmpty {
                    Text(group.1.uppercased()).font(Theme.font(18, .heavy)).tracking(0.8).foregroundStyle(Theme.muted)
                        .padding(.top, 6)
                    ForEach(rows) { row($0) }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func dot(_ s: SecurityOverview.Sensor) -> Color {
        if !s.available { return Theme.muted }
        if !s.active { return .green }
        return s.group == "motion" ? .blue : s.group == "environment" ? Theme.danger : .orange
    }

    private func row(_ s: SecurityOverview.Sensor) -> some View {
        HStack(spacing: 14) {
            Circle().fill(dot(s)).frame(width: 14, height: 14)
            Text(s.name).font(Theme.font(24, .bold)).foregroundStyle(Theme.text).lineLimit(1)
            if s.armed { Image(systemName: "lock.fill").font(.system(size: 18)).foregroundStyle(Theme.muted) }
            Spacer(minLength: 8)
            Text(s.label).font(Theme.font(24, .heavy)).foregroundStyle(s.active ? dot(s) : Theme.text)
        }
    }
}

/// A camera tile: its picture, with the live video over it while the tab is showing.
private struct TVCameraTile: View {
    @Environment(AppModel.self) private var model
    let cam: SecurityOverview.Camera
    let person: Bool
    let live: Bool

    var body: some View {
        ZStack {
            CameraStill(path: cam.snapshot_url, width: 960)
            if live, let path = cam.video_url, let api = model.api, let url = api.resolve(path) {
                CameraVideo(url: url, token: api.token).id(cam.entity_id)
            }
        }
        .aspectRatio(16 / 9, contentMode: .fit)
        .overlay(alignment: .bottomLeading) {
            Text(cam.name).font(Theme.font(22, .heavy)).foregroundStyle(.white)
                .padding(.horizontal, 16).padding(.vertical, 8)
                .background(.black.opacity(0.55), in: Capsule())
                .padding(16)
        }
        .overlay(alignment: .topTrailing) {
            if person {
                Text("Person").font(Theme.font(22, .heavy)).foregroundStyle(.white)
                    .padding(.horizontal, 16).padding(.vertical, 8)
                    .background(Theme.danger, in: Capsule())
                    .padding(16)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay {
            if person { RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(Theme.danger, lineWidth: 5) }
        }
    }
}

/// A camera full screen at full resolution: its picture straight away, then the live video over it. Menu closes it.
private struct TVCameraFull: View {
    @Environment(AppModel.self) private var model
    let cam: SecurityOverview.Camera

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.black
            CameraStill(path: cam.snapshot_url, width: 1920, contentMode: .fit)
            if let path = cam.video_hd_url ?? cam.video_url, let api = model.api, let url = api.resolve(path) {
                CameraVideo(url: url, token: api.token)
            }
            Text(cam.name).font(Theme.font(30, .heavy)).foregroundStyle(.white)
                .padding(.horizontal, 22).padding(.vertical, 10)
                .background(.black.opacity(0.55), in: Capsule())
                .padding(60)
        }
        .ignoresSafeArea()
    }
}
