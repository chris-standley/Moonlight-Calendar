import Foundation

/// For calls whose answer we don't need: decodes any JSON.
struct Ignored: Decodable {
    init(from decoder: Decoder) throws {}
}

enum APIError: LocalizedError {
    case unpaired
    case wrongPin
    case server(String)

    var errorDescription: String? {
        switch self {
        case .unpaired: "This Apple TV is not paired"
        case .wrongPin: "That PIN isn't right"
        case .server(let detail): detail
        }
    }
}

/// Talks to the Moonlight add-on with this device's display token: on its home-network port (8091 by default), or
/// away from home on its https address.
struct APIClient: Sendable {
    var baseURL: URL
    let token: String?
    /// The screen layout this Apple TV was approved as; picks which speaker its Now playing card shows.
    var layout = "large"

    private static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.httpCookieAcceptPolicy = .never
        return URLSession(configuration: config)
    }()

    /// Whether a Moonlight answers at `url` within `timeout` seconds.
    static func answers(_ url: URL, timeout: TimeInterval) async -> Bool {
        var req = URLRequest(url: APIClient(baseURL: url, token: nil).url("/api/health"))
        req.timeoutInterval = timeout
        guard let (data, response) = try? await session.data(for: req),
              (response as? HTTPURLResponse)?.statusCode == 200 else { return false }
        return (try? JSONDecoder().decode(Health.self, from: data))?.ok == true
    }

    func url(_ path: String, query: [String: String] = [:]) -> URL {
        var comps = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        comps.path = path.hasPrefix("/") ? path : "/" + path
        if !query.isEmpty {
            comps.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        return comps.url!
    }

    /// An absolute API path the server handed out (photo and album-art urls), resolved against the add-on.
    func resolve(_ pathOrURL: String) -> URL? {
        if let u = URL(string: pathOrURL), u.scheme != nil { return u }
        return URL(string: pathOrURL, relativeTo: baseURL)?.absoluteURL
    }

    func request(_ url: URL, method: String = "GET", body: [String: Any]? = nil) -> URLRequest {
        var req = URLRequest(url: url)
        req.httpMethod = method
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        return req
    }

    func data(for req: URLRequest) async throws -> Data {
        let (data, response) = try await Self.session.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            if status == 401 { throw APIError.unpaired }
            if status == 403 { throw APIError.wrongPin }
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError.server(detail ?? HTTPURLResponse.localizedString(forStatusCode: status))
        }
        return data
    }

    func get<T: Decodable>(_ path: String, _ query: [String: String] = [:]) async throws -> T {
        let data = try await data(for: request(url(path, query: query)))
        return try JSONDecoder().decode(T.self, from: data)
    }

    @discardableResult
    func send<T: Decodable>(_ method: String, _ path: String, _ body: [String: Any]? = nil, query: [String: String] = [:]) async throws -> T {
        let data = try await data(for: request(url(path, query: query), method: method, body: body))
        return try JSONDecoder().decode(T.self, from: data)
    }

    // MARK: Endpoints (see API.md)

    func health() async throws -> Health { try await get("/api/health") }
    func authStatus() async throws -> AuthStatus { try await get("/api/auth/status") }
    func pairStart(layout: String, name: String) async throws -> PairStart {
        try await send("POST", "/api/pair/start", ["layout": layout, "name": name])
    }
    func pairPoll(_ id: String) async throws -> PairPoll { try await get("/api/pair/\(id)") }

    func settings() async throws -> Settings { try await get("/api/settings") }
    func people() async throws -> [Person] { try await get("/api/people") }
    func events(_ start: String, _ end: String) async throws -> [Occurrence] {
        try await get("/api/events", ["start": start, "end": end])
    }
    func weather() async throws -> Weather { try await get("/api/weather") }
    func chores(_ date: String) async throws -> [ChoreDay] { try await get("/api/chores", ["date": date]) }
    func setChore(_ id: String, date: String, done: Bool) async throws {
        if done {
            let _: Ignored = try await send("POST", "/api/chores/\(id)/complete", ["date": date])
        } else {
            let _: Ignored = try await send("DELETE", "/api/chores/\(id)/complete", query: ["date": date])
        }
    }
    func points() async throws -> [Balance] { try await get("/api/points") }
    func ledger(_ personId: String) async throws -> [LedgerEntry] { try await get("/api/points/\(personId)/ledger") }
    func rewards() async throws -> [Reward] { try await get("/api/rewards") }
    func redeem(_ rewardId: String, personId: String, pin: String) async throws -> Int {
        let r: BalanceResponse = try await send("POST", "/api/rewards/\(rewardId)/redeem", ["person_id": personId, "pin": pin])
        return r.balance
    }
    func lists() async throws -> [TaskList] { try await get("/api/lists") }
    func items(_ listId: String) async throws -> [ListItem] { try await get("/api/lists/\(listId)/items") }
    func setItem(_ id: String, done: Bool) async throws {
        let _: Ignored = try await send("PATCH", "/api/items/\(id)", ["done": done])
    }
    func meals(_ start: String, _ end: String) async throws -> [Meal] {
        try await get("/api/meals", ["start": start, "end": end])
    }
    func nowPlaying() async throws -> NowPlaying { try await get("/api/media/now-playing", ["layout": layout]) }
    func media(_ action: String) async throws -> NowPlaying {
        try await send("POST", "/api/media/command", ["layout": layout, "action": action])
    }
    func photos() async throws -> PhotoList { try await get("/api/screensaver/photos") }
    func nursery() async throws -> NurseryConfig { try await get("/api/nursery") }
    func nurseryUpdates() async throws -> [NurseryUpdate] { try await get("/api/nursery/updates") }

    // MARK: Editing (phone and tablet; the TV only ticks things off)

    func verifyPin(_ pin: String) async throws -> Bool {
        let r: [String: Bool] = try await send("POST", "/api/pin/verify", ["pin": pin])
        return r["ok"] ?? false
    }
    func saveEvent(id: String?, _ body: [String: Any]) async throws {
        let _: Ignored = try await send(id == nil ? "POST" : "PATCH", id.map { "/api/events/\($0)" } ?? "/api/events", body)
    }
    func deleteEvent(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/events/\(id)")
    }
    func saveChore(id: String?, _ body: [String: Any]) async throws {
        let _: Ignored = try await send(id == nil ? "POST" : "PATCH", id.map { "/api/chores/\($0)" } ?? "/api/chores", body)
    }
    func deleteChore(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/chores/\(id)")
    }
    func adjustPoints(_ personId: String, change: Int, reason: String, pin: String) async throws {
        let _: Ignored = try await send("POST", "/api/points/adjust", ["person_id": personId, "change": change, "reason": reason, "pin": pin])
    }
    func createReward(title: String, emoji: String, cost: Int, personId: String?) async throws {
        let _: Ignored = try await send("POST", "/api/rewards", ["title": title, "emoji": emoji, "cost": cost, "person_id": personId.map { $0 as Any } ?? NSNull()])
    }
    func deleteReward(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/rewards/\(id)")
    }
    func createList(name: String, emoji: String, color: String, kind: String) async throws {
        let _: Ignored = try await send("POST", "/api/lists", ["name": name, "emoji": emoji, "color": color, "kind": kind])
    }
    func deleteList(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/lists/\(id)")
    }
    func addItem(_ listId: String, title: String) async throws {
        let _: Ignored = try await send("POST", "/api/lists/\(listId)/items", ["title": title])
    }
    func deleteItem(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/items/\(id)")
    }
    func clearDone(_ listId: String) async throws {
        let _: Ignored = try await send("POST", "/api/lists/\(listId)/clear-done")
    }
    func saveMeal(id: String?, _ body: [String: Any]) async throws {
        let _: Ignored = try await send(id == nil ? "POST" : "PATCH", id.map { "/api/meals/\($0)" } ?? "/api/meals", body)
    }
    func deleteMeal(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/meals/\(id)")
    }

    /// `/api/ws` with the token in the query (the WebSocket can't send an Authorization header everywhere).
    func webSocketURL() -> URL {
        var comps = URLComponents(url: url("/api/ws", query: token.map { ["token": $0] } ?? [:]), resolvingAgainstBaseURL: false)!
        comps.scheme = baseURL.scheme == "https" ? "wss" : "ws"
        return comps.url!
    }
}
