import SwiftUI

/// Security: the alarm (arm it, or disarm it with its code, which goes straight to Home Assistant and is never kept),
/// its sensors, and the cameras (pictures every couple of seconds; tap one for live video). As on the wall screens.
struct SecurityScreen: View {
    @Environment(AppModel.self) private var model
    @State private var data: SecurityOverview?
    @State private var watching: SecurityOverview.Camera?

    var body: some View {
        Page(title: "Security") { room in
            ScrollView {
                VStack(spacing: 16) {
                    if let data {
                        if !data.configured {
                            EmptyHint(text: "Security shows your alarm, its sensors and your cameras from Home Assistant. It needs Moonlight running as the Home Assistant add-on.")
                        } else {
                            if !data.reachable {
                                Text("Can't reach Home Assistant").font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.danger)
                            }
                            if room == .narrow {
                                if let alarm = data.alarm { AlarmCard(alarm: alarm, reload: load) }
                                cameras(data, columns: 1)
                                SensorsCard(sensors: data.sensors)
                            } else {
                                HStack(alignment: .top, spacing: 16) {
                                    VStack(spacing: 16) {
                                        if let alarm = data.alarm { AlarmCard(alarm: alarm, reload: load) }
                                        SensorsCard(sensors: data.sensors)
                                    }
                                    .frame(maxWidth: 440)
                                    cameras(data, columns: room == .wide ? 2 : 1)
                                }
                            }
                        }
                    } else {
                        ProgressView().padding(40)
                    }
                }
                .padding(16)
                .frame(maxWidth: 1400)
                .frame(maxWidth: .infinity)
            }
        } tools: {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("Refresh")
            }
        }
        // Moonlight says when the alarm or a sensor changes.
        .task(id: model.rev("security", "security_alert", "settings")) { await load() }
        .fullScreenCover(item: $watching) { CameraFull(cam: $0) }
    }

    @ViewBuilder
    private func cameras(_ data: SecurityOverview, columns: Int) -> some View {
        let cams = data.cameras
        if !cams.isEmpty {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: columns), spacing: 12) {
                ForEach(cams) { cam in
                    Button { watching = cam } label: { CameraTile(cam: cam, person: data.seesPerson(cam)) }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Watch \(cam.name)")
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func load() async {
        if let d = await model.call({ try await $0.security() }) { data = d }
    }
}

private func ago(_ iso: String?) -> String? { SecurityOverview.ago(iso) }

/// The alarm: its state, who changed it and when, what's open, and buttons to arm it in each mode it offers or to
/// disarm it. Disarming asks for the alarm code; arming asks only if the panel needs one.
private struct AlarmCard: View {
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
        Card {
            HStack(spacing: 12) {
                Image(systemName: alarm.armed ? "lock.shield.fill" : alarm.state == "disarmed" ? "checkmark.shield" : "shield.lefthalf.filled")
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(color)
                VStack(alignment: .leading, spacing: 2) {
                    Text(alarm.label).font(Theme.text(.title2, .heavy)).foregroundStyle(Theme.text)
                    if let when = ago(alarm.last_changed) {
                        Text(alarm.changed_by.map { "\(when) by \($0)" } ?? when)
                            .font(Theme.text(.caption)).foregroundStyle(Theme.muted)
                    }
                }
                Spacer()
                if busy { ProgressView() }
            }
            if !alarm.open_sensors.isEmpty {
                Text("Open: \(alarm.open_sensors.joined(separator: ", "))")
                    .font(Theme.text(.subheadline, .heavy)).foregroundStyle(.orange)
            }
            if let message {
                Text(message).font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.danger)
            }
            if alarm.available {
                if alarm.state == "disarmed" {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 8)], spacing: 8) {
                        ForEach(alarm.modes, id: \.self) { mode in
                            Button(SecurityOverview.armLabel[mode] ?? "Arm \(mode)") { start(mode) }
                                .buttonStyle(.borderedProminent)
                                .frame(maxWidth: .infinity)
                        }
                    }
                } else {
                    Button("Disarm", role: .destructive) { start("disarm") }
                        .buttonStyle(.borderedProminent)
                        .tint(Theme.danger)
                }
            }
        }
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

/// The alarm's sensors, grouped like the wall screens: doors, windows, motion, smoke and leaks.
private struct SensorsCard: View {
    let sensors: [SecurityOverview.Sensor]

    private static let groups = [("doors", "Doors"), ("windows", "Windows"), ("motion", "Motion"),
                                 ("environment", "Smoke and leaks"), ("other", "Other")]

    var body: some View {
        if !sensors.isEmpty {
            Card {
                ForEach(Self.groups, id: \.0) { group in
                    let rows = sensors.filter { $0.group == group.0 }
                    if !rows.isEmpty {
                        Text(group.1.uppercased()).font(Theme.text(.caption, .heavy)).foregroundStyle(Theme.muted)
                        ForEach(rows) { row($0) }
                    }
                }
            }
        }
    }

    private func dot(_ s: SecurityOverview.Sensor) -> Color {
        if !s.available { return Theme.muted }
        if !s.active { return .green }
        return s.group == "motion" ? .blue : s.group == "environment" ? Theme.danger : .orange
    }

    private func row(_ s: SecurityOverview.Sensor) -> some View {
        HStack(spacing: 10) {
            Circle().fill(dot(s)).frame(width: 10, height: 10)
            Text(s.name).font(Theme.text(.subheadline)).foregroundStyle(Theme.text).lineLimit(1)
            if s.armed { Image(systemName: "lock.fill").font(.caption).foregroundStyle(Theme.muted) }
            Spacer(minLength: 8)
            Text(s.label).font(Theme.text(.subheadline, .heavy)).foregroundStyle(s.active ? dot(s) : Theme.text)
            if let when = ago(s.last_changed) {
                Text(when).font(Theme.text(.caption)).foregroundStyle(Theme.muted).frame(minWidth: 70, alignment: .trailing)
            }
        }
        .padding(.vertical, 2)
    }
}

private struct CameraTile: View {
    let cam: SecurityOverview.Camera
    let person: Bool

    var body: some View {
        CameraStill(path: cam.snapshot_url, width: 800)
            .aspectRatio(16 / 9, contentMode: .fit)
            .overlay(alignment: .bottomLeading) {
                Text(cam.name).font(Theme.text(.caption, .heavy)).foregroundStyle(.white)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(.black.opacity(0.55), in: Capsule())
                    .padding(10)
            }
            .overlay(alignment: .topTrailing) {
                if person {
                    Text("Person").font(Theme.text(.caption, .heavy)).foregroundStyle(.white)
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .background(Theme.danger, in: Capsule())
                        .padding(10)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

/// A camera full screen: its picture straight away, then the live video over it once the stream is playing.
private struct CameraFull: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let cam: SecurityOverview.Camera

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            ZStack {
                CameraStill(path: cam.snapshot_url, width: 1280, contentMode: .fit)
                if let path = cam.video_hd_url ?? cam.video_url, let api = model.api, let url = api.resolve(path) {
                    CameraVideo(url: url, token: api.token)
                }
            }
            .ignoresSafeArea()
            HStack(spacing: 12) {
                Text(cam.name).font(Theme.text(.headline, .heavy)).foregroundStyle(.white)
                Button { dismiss() } label: {
                    Image(systemName: "xmark").font(.headline).foregroundStyle(.white)
                        .frame(width: 40, height: 40).background(.black.opacity(0.55), in: Circle())
                }
                .accessibilityLabel("Close")
            }
            .padding(16)
        }
    }
}
