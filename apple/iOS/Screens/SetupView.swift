import AuthenticationServices
import SwiftUI

/// First run: find Moonlight on the home network (or type its address), then pair with a 6-digit code that
/// someone approves on a screen that's already signed in (Settings › Screens).
struct SetupView: View {
    @State private var discovery = Discovery()
    @State private var server: URL?
    @State private var address = ""
    @State private var checking = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    if let server {
                        PairingCard(server: server) { self.server = nil }
                    } else {
                        find
                    }
                }
                .padding(24)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
            }
            .background(Theme.bg.ignoresSafeArea())
        }
        .onAppear { discovery.start() }
        .onDisappear { discovery.stop() }
    }

    private var find: some View {
        VStack(spacing: 22) {
            LogoMark(size: 88).padding(.top, 30)
            VStack(spacing: 6) {
                Text("Welcome to Moonlight").font(Theme.text(.largeTitle, .heavy))
                Text(discovery.servers.isEmpty ? "Looking for Moonlight on your home network…" : "Choose your Moonlight")
                    .font(Theme.text(.headline)).foregroundStyle(Theme.muted)
            }
            .multilineTextAlignment(.center)
            VStack(spacing: 10) {
                ForEach(discovery.servers) { s in
                    Button { server = s.url } label: {
                        HStack(spacing: 14) {
                            Image(systemName: "house.fill").font(.title2).foregroundStyle(Theme.accent)
                            VStack(alignment: .leading) {
                                Text(s.host).font(Theme.text(.headline, .heavy)).foregroundStyle(Theme.text)
                                Text("Moonlight \(s.version ?? "")").font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").foregroundStyle(Theme.muted)
                        }
                        .padding(16)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
                if discovery.searching && discovery.servers.isEmpty { ProgressView().padding() }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("Or enter the address").font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.muted)
                HStack {
                    TextField("homeassistant.local:\(Discovery.defaultPort)", text: $address)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .submitLabel(.go)
                        .onSubmit { Task { await connect() } }
                        .padding(12)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    Button(checking ? "…" : "Connect") { Task { await connect() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(address.isEmpty || checking)
                }
                if let error { Text(error).font(Theme.text(.footnote)).foregroundStyle(Theme.danger) }
            }
            Button("Search again") { discovery.start() }.font(Theme.text(.subheadline, .bold))
        }
    }

    /// Accepts "192.168.1.5", "homeassistant.local:8091", "moonlight.example.com" (its https address) or a full URL.
    private func connect() async {
        let text = address.trimmingCharacters(in: .whitespaces)
        let candidates = Self.candidates(text)
        guard !candidates.isEmpty else {
            error = "That doesn't look like an address."
            return
        }
        checking = true
        defer { checking = false }
        for url in candidates where await APIClient.answers(url, timeout: 6) {
            error = nil
            server = url
            return
        }
        error = "No Moonlight answered at \(text). Check the address and port (add-on › Configuration › Network)."
    }

    /// The URLs to try for what was typed: a home address over http on 8091, a domain name over https first.
    static func candidates(_ text: String) -> [URL] {
        func url(_ scheme: String, _ rest: String, defaultPort: Int?) -> URL? {
            guard var comps = URLComponents(string: "\(scheme)://\(rest)"), let host = comps.host, !host.isEmpty else { return nil }
            if comps.port == nil, let defaultPort { comps.port = defaultPort }
            comps.path = ""
            comps.query = nil
            return comps.url
        }
        if text.contains("://") {
            let scheme = text.lowercased().hasPrefix("https://") ? "https" : "http"
            let rest = String(text.split(separator: "/", maxSplits: 2, omittingEmptySubsequences: false).dropFirst(2).first ?? "")
            return [url(scheme, rest, defaultPort: scheme == "http" ? Discovery.defaultPort : nil)].compactMap { $0 }
        }
        let host = text.split(separator: ":").first.map(String.init)?.lowercased() ?? ""
        let home = host.hasSuffix(".local") || host.allSatisfy { $0.isNumber || $0 == "." } || !host.contains(".")
        let https = url("https", text, defaultPort: nil)
        let http = url("http", text, defaultPort: Discovery.defaultPort)
        return (home ? [http, https] : [https, http]).compactMap { $0 }
    }
}

struct PairingCard: View {
    @Environment(AppModel.self) private var model
    @Environment(\.webAuthenticationSession) private var webAuth
    let server: URL
    let onBack: () -> Void
    @State private var code: String?
    @State private var expires = Date()
    @State private var error: String?
    @State private var haLogin = false
    @State private var signingIn = false

    var body: some View {
        VStack(spacing: 22) {
            LogoMark(size: 72).padding(.top, 30)
            Text("Pair this \(UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone")").font(Theme.text(.title, .heavy))
            Text("On a wall screen or in the Home Assistant sidebar, open Moonlight › Settings › Screens › Pair and enter this code.")
                .font(Theme.text(.body)).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
            HStack(spacing: 8) {
                ForEach(Array((code ?? "      ").enumerated()), id: \.offset) { item in
                    Text(String(item.element))
                        .font(.system(size: 40, weight: .heavy, design: .rounded).monospacedDigit())
                        .frame(width: 46, height: 64)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            .accessibilityElement()
            .accessibilityLabel("Pairing code \((code ?? "").map { String($0) }.joined(separator: " "))")
            .textSelection(.enabled)
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                let left = max(0, Int(expires.timeIntervalSince(ctx.date)))
                Text(error ?? (code == nil ? "Getting a code…" : "New code in \(left / 60):\(String(format: "%02d", left % 60))"))
                    .font(Theme.text(.footnote)).foregroundStyle(error == nil ? Theme.muted : Theme.danger)
            }
            if haLogin {
                VStack(spacing: 8) {
                    Text("or").font(Theme.text(.subheadline, .bold)).foregroundStyle(Theme.muted)
                    Button { Task { await signInWithHomeAssistant() } } label: {
                        Label("Sign in with Home Assistant", systemImage: "house.circle.fill").frame(maxWidth: 320)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(signingIn)
                }
            }
            Button("Choose another Moonlight", action: onBack).font(Theme.text(.subheadline, .bold))
        }
        .task(id: server) { await pairLoop() }
        .task(id: server) { haLogin = (try? await APIClient(baseURL: server, token: nil).health())?.ha_login == true }
    }

    /// Home Assistant's own login page in a sign-in sheet; Moonlight hands this device a token when it's done.
    private func signInWithHomeAssistant() async {
        let name = UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
        let api = APIClient(baseURL: server, token: nil)
        let start = api.url("/api/auth/ha/start", query: ["layout": "phone", "name": name, "app": "1"])  // pairs as an "app" device
        signingIn = true
        defer { signingIn = false }
        do {
            let back = try await webAuth.authenticate(using: start, callbackURLScheme: "moonlight",
                                                      preferredBrowserSession: .ephemeral)
            let items = URLComponents(url: back, resolvingAgainstBaseURL: false)?.queryItems ?? []
            guard let token = items.first(where: { $0.name == "token" })?.value else {
                error = "Home Assistant didn't finish signing in."
                return
            }
            await model.paired(server: server, token: token)
        } catch let e as ASWebAuthenticationSessionError where e.code == .canceledLogin {
            return
        } catch {
            self.error = "Couldn't sign in with Home Assistant."
        }
    }

    private func pairLoop() async {
        let api = APIClient(baseURL: server, token: nil)
        let name = UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
        while !Task.isCancelled {
            do {
                let start = try await api.pairStart(layout: "app", name: name)
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
                self.error = "Can't reach Moonlight. Retrying…"
                code = nil
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }
}
