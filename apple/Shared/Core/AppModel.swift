import Foundation
import Observation
import SwiftUI

/// App-wide state: the paired add-on, the family, settings, and a revision counter per live-update topic.
/// Views reload with `.task(id: model.rev("events"))` so a change on any screen shows here within a second.
@Observable
@MainActor
final class AppModel {
    enum Phase: Equatable { case starting, setup, ready }

    private(set) var phase: Phase = .starting
    private(set) var api: APIClient?
    private(set) var people: [Person] = []
    private(set) var settings: Settings?
    private(set) var weather: Weather?
    private(set) var connected = false
    private var revisions: [String: Int] = [:]
    private var socket: URLSessionWebSocketTask?
    private var liveTask: Task<Void, Never>?

    var dates: Dates { Dates(timezone: settings?.timezone) }
    var kids: [Person] { people.filter(\.isChild) }
    func person(_ id: String?) -> Person? { people.first { $0.id == id } }

    /// Sum of the topics' revisions: changes whenever any of them is broadcast.
    func rev(_ topics: String...) -> Int { topics.reduce(0) { $0 + (revisions[$1] ?? 0) } }

    func bump(_ topic: String) { revisions[topic, default: 0] += 1 }

    // MARK: Session

    func start() async {
        guard let server = Credentials.server, let token = Credentials.token else {
            phase = .setup
            return
        }
        var api = APIClient(baseURL: server, token: token)
        do {
            let status = try await api.authStatus()
            if status.required && !status.authorised { return forget() }
            if let layout = status.display?.layout, layout != "service" { api.layout = layout }
        } catch {
            // Add-on unreachable (restarting, network down): keep the pairing and carry on; data loads retry.
        }
        self.api = api
        phase = .ready
        await loadBasics()
        connectLive()
    }

    func paired(server: URL, token: String) async {
        Credentials.server = server
        Credentials.token = token
        await start()
    }

    /// Any 401: this Apple TV was removed in Settings › Screens. Back to pairing.
    func forget() {
        liveTask?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        Credentials.token = nil
        api = nil
        people = []
        settings = nil
        phase = .setup
    }

    /// Run an API call; a 401 sends the app back to pairing, other errors come back as nil.
    func call<T>(_ body: (APIClient) async throws -> T) async -> T? {
        guard let api else { return nil }
        do {
            return try await body(api)
        } catch APIError.unpaired {
            forget()
        } catch {
            if !(error is CancellationError) { print("Moonlight:", error.localizedDescription) }
        }
        return nil
    }

    func loadBasics() async {
        if let p = await call({ try await $0.people() }) { people = p }
        if let s = await call({ try await $0.settings() }) { settings = s }
        if let w = await call({ try await $0.weather() }) { weather = w }
    }

    // MARK: Live updates (`/api/ws`)

    private func connectLive() {
        liveTask?.cancel()
        liveTask = Task { [weak self] in
            var delay: Double = 2
            while !Task.isCancelled {
                guard let self, let api = self.api else { return }
                let ws = URLSession.shared.webSocketTask(with: api.webSocketURL())
                self.socket = ws
                ws.resume()
                let pinger = Task {
                    while !Task.isCancelled {
                        try? await Task.sleep(for: .seconds(25))
                        try? await ws.send(.string("ping"))
                    }
                }
                do {
                    while !Task.isCancelled {
                        let msg = try await ws.receive()
                        self.connected = true
                        delay = 2
                        if case .string(let text) = msg { await self.handle(text) }
                    }
                } catch {
                    self.connected = false
                }
                pinger.cancel()
                ws.cancel()
                // Status check: a revoked screen gets its socket closed, so find out whether we're still paired.
                if case .some(.some(let status)) = await self.call({ try? await $0.authStatus() }),
                   status.required && !status.authorised {
                    self.forget()
                    return
                }
                try? await Task.sleep(for: .seconds(delay))
                delay = min(delay * 2, 60)
                // Catch up on anything missed while disconnected.
                for topic in ["people", "events", "chores", "points", "rewards", "lists", "meals", "settings", "photos", "media"] {
                    self.bump(topic)
                }
                await self.loadBasics()
            }
        }
    }

    private func handle(_ text: String) async {
        guard let data = text.data(using: .utf8),
              let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              msg["type"] as? String == "changed", let topic = msg["topic"] as? String else { return }
        bump(topic)
        switch topic {
        case "people": if let p = await call({ try await $0.people() }) { people = p }
        case "settings": if let s = await call({ try await $0.settings() }) { settings = s }
        default: break
        }
    }

    /// Weather changes slowly and isn't broadcast: refresh it every 15 minutes while the app runs.
    func refreshWeatherPeriodically() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(900))
            if let w = await call({ try await $0.weather() }) { weather = w }
        }
    }
}
