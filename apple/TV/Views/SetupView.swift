import SwiftUI

/// First run (or after this Apple TV is removed in Settings › Screens): find the add-on, then pair with a code.
/// Nothing here needs the on-screen keyboard: the server is found on the network, or picked with the remote.
struct SetupView: View {
    @Environment(AppModel.self) private var model
    @State private var discovery = Discovery()
    @State private var server: URL?
    @State private var manual = false

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            if let server {
                PairingView(server: server) { self.server = nil }
            } else if manual {
                AddressPicker { url in
                    manual = false
                    server = url
                } onCancel: { manual = false }
            } else {
                findView
            }
        }
        .onAppear { discovery.start() }
        .onDisappear { discovery.stop() }
    }

    private var findView: some View {
        VStack(spacing: 44) {
            LogoMark(size: 150)
            VStack(spacing: 14) {
                Text("Welcome to Moonlight").font(Theme.font(64, .heavy)).foregroundStyle(Theme.text)
                Text(discovery.servers.isEmpty
                     ? "Looking for Moonlight on your home network…"
                     : "Choose your Moonlight to pair this Apple TV.")
                    .font(Theme.font(32, .bold)).foregroundStyle(Theme.muted)
            }
            VStack(spacing: 24) {
                ForEach(discovery.servers) { s in
                    Button { server = s.url } label: {
                        HStack(spacing: 24) {
                            Image(systemName: "house.fill").font(.system(size: 40)).foregroundStyle(Theme.accent)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(s.host).font(Theme.font(34, .heavy)).foregroundStyle(Theme.text)
                                Text("Moonlight \(s.version ?? "")").font(Theme.font(24, .bold)).foregroundStyle(Theme.muted)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.system(size: 30, weight: .bold)).foregroundStyle(Theme.muted)
                        }
                        .padding(.horizontal, 36)
                        .frame(width: 900, height: 120)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    }
                    .buttonStyle(.moonCard(radius: 24))
                }
                if discovery.searching && discovery.servers.isEmpty { ProgressView().padding() }
            }
            .frame(minHeight: 160)
            HStack(spacing: 30) {
                Button("Search again") { discovery.start() }.buttonStyle(.pill)
                Button("Enter address") { manual = true }.buttonStyle(.pill)
            }
            Text("Moonlight runs as a Home Assistant add-on, on port \(Discovery.defaultPort) unless you changed it.")
                .font(Theme.font(24, .semibold)).foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Shows a 6-digit code an adult approves in Moonlight › Settings › Screens, then stores the token.
struct PairingView: View {
    @Environment(AppModel.self) private var model
    let server: URL
    let onBack: () -> Void
    @State private var code: String?
    @State private var expires = Date()
    @State private var error: String?

    var body: some View {
        VStack(spacing: 50) {
            LogoMark(size: 110)
            VStack(spacing: 16) {
                Text("Pair this Apple TV").font(Theme.font(60, .heavy)).foregroundStyle(Theme.text)
                Text("On your phone or a wall screen, open Moonlight › Settings › Screens › Pair a new screen, and enter this code.")
                    .font(Theme.font(32, .bold)).foregroundStyle(Theme.muted)
                    .multilineTextAlignment(.center).frame(maxWidth: 1200)
            }
            HStack(spacing: 22) {
                ForEach(Array((code ?? "      ").enumerated()), id: \.offset) { item in
                    Text(String(item.element))
                        .font(.system(size: 110, weight: .heavy, design: .rounded).monospacedDigit())
                        .foregroundStyle(Theme.text)
                        .frame(width: 130, height: 170)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
                        .shadow(color: .black.opacity(0.08), radius: 14, y: 6)
                }
            }
            .accessibilityElement()
            .accessibilityLabel("Pairing code \(spokenCode)")
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                let left = max(0, Int(expires.timeIntervalSince(ctx.date)))
                Text(error ?? (code == nil ? "Getting a code…" : "\(server.host ?? "") · new code in \(left / 60):\(String(format: "%02d", left % 60))"))
                    .font(Theme.font(26, .bold))
                    .foregroundStyle(error == nil ? Theme.muted : Theme.danger)
            }
            Button("Choose another Moonlight", action: onBack).buttonStyle(.pill)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: server) { await pairLoop() }
    }

    /// "1 2 3 4 5 6", so VoiceOver reads digits rather than a number.
    private var spokenCode: String {
        (code ?? "").map { String($0) }.joined(separator: " ")
    }

    private func pairLoop() async {
        let api = APIClient(baseURL: server, token: nil)
        while !Task.isCancelled {
            do {
                let start = try await api.pairStart(layout: "hallway", name: "Apple TV")
                code = start.code
                expires = Date().addingTimeInterval(TimeInterval(start.expires_in))
                error = nil
                while !Task.isCancelled && Date() < expires {
                    try await Task.sleep(for: .seconds(2))
                    let poll = try await api.pairPoll(start.pair_id)
                    if poll.status == "approved", let token = poll.token {
                        await model.paired(server: server, token: token)
                        return
                    }
                    if poll.status == "expired" { break }
                }
            } catch is CancellationError {
                return
            } catch {
                self.error = "Can't reach Moonlight at \(server.host ?? ""). Retrying…"
                code = nil
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }
}

/// Picks an IPv4 address with the remote: each part goes up or down with the arrows, left/right moves between parts.
/// Prefilled with this Apple TV's own network, so usually only the last number changes.
struct AddressPicker: View {
    let onDone: (URL) -> Void
    let onCancel: () -> Void
    @State private var parts: [Int] = Discovery.localIPv4().map { [$0[0], $0[1], $0[2], 1] } ?? [192, 168, 1, 1]
    @State private var port = Discovery.defaultPort
    @State private var checking = false
    @State private var error: String?
    @FocusState private var focused: Int?

    var body: some View {
        VStack(spacing: 50) {
            VStack(spacing: 14) {
                Text("Moonlight's address").font(Theme.font(60, .heavy)).foregroundStyle(Theme.text)
                Text("Use your Home Assistant's address and Moonlight's port. Swipe up or down to change a number, left or right to move.")
                    .font(Theme.font(30, .bold)).foregroundStyle(Theme.muted)
                    .multilineTextAlignment(.center).frame(maxWidth: 1200)
            }
            // Everything focusable sits on one row: up/down only ever change a number, never move focus away.
            HStack(spacing: 12) {
                Button("Back", action: onCancel).buttonStyle(.pill).padding(.trailing, 16)
                ForEach(0..<4, id: \.self) { i in
                    if i > 0 { Text(".").font(Theme.font(70, .heavy)).foregroundStyle(Theme.muted) }
                    OctetField(value: $parts[i], focused: focused == i)
                        .focused($focused, equals: i)
                }
                Text(":").font(Theme.font(70, .heavy)).foregroundStyle(Theme.muted)
                OctetField(value: $port, range: 1...65535, width: 260, label: "Port", focused: focused == 4)
                    .focused($focused, equals: 4)
                Button(checking ? "Checking…" : "Connect") { Task { await connect() } }
                    .buttonStyle(.pillProminent)
                    .disabled(checking)
                    .padding(.leading, 16)
            }
            Text(error ?? " ").font(Theme.font(26, .bold)).foregroundStyle(Theme.danger)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { focused = 3 }
    }

    private func connect() async {
        let host = parts.map(String.init).joined(separator: ".")
        guard let url = URL(string: "http://\(host):\(port)") else { return }
        checking = true
        defer { checking = false }
        if let h = try? await APIClient(baseURL: url, token: nil).health(), h.ok {
            onDone(url)
        } else {
            error = "No Moonlight found at \(host):\(port). Check the address, the port (add-on › Configuration › Network) and that it's running."
        }
    }
}

/// One number of the address (or the port). Up/down change it, left/right move on as usual.
private struct OctetField: View {
    @Binding var value: Int
    var range: ClosedRange<Int> = 0...255
    var width: CGFloat = 160
    var label = "Address part"
    let focused: Bool

    private func step(_ n: Int) {
        let span = range.count
        value = range.lowerBound + ((value - range.lowerBound + n) % span + span) % span
    }

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "chevron.up").opacity(focused ? 1 : 0)
            Text("\(value)")
                .font(.system(size: 72, weight: .heavy, design: .rounded).monospacedDigit())
                .frame(width: width, height: 130)
                .background(focused ? Theme.accent : Theme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                .foregroundStyle(focused ? Color.white : Theme.text)
                .scaleEffect(focused ? 1.08 : 1)
                .shadow(color: .black.opacity(focused ? 0.2 : 0.06), radius: focused ? 20 : 8, y: 6)
            Image(systemName: "chevron.down").opacity(focused ? 1 : 0)
        }
        .font(.system(size: 30, weight: .bold))
        .foregroundStyle(Theme.muted)
        .animation(.easeOut(duration: 0.15), value: focused)
        .focusable()
        .onMoveCommand { dir in
            switch dir {
            case .up: step(1)
            case .down: step(-1)
            default: break
            }
        }
        .accessibilityElement()
        .accessibilityLabel(label)
        .accessibilityValue("\(value)")
        .accessibilityAdjustableAction { dir in
            switch dir {
            case .increment: step(1)
            case .decrement: step(-1)
            @unknown default: break
            }
        }
    }
}
