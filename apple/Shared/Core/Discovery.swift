import Foundation
import Network
import Observation

/// Finds the Moonlight add-on on the home network without typing anything.
///
/// Home Assistant advertises itself over Bonjour (`_home-assistant._tcp`, with its address in the TXT record),
/// and Moonlight's direct port is on the same host: 8091 by default (8099 before 0.3.1). The host port can be changed in
/// the add-on's Network settings; anything else is picked in the address picker. We also try `homeassistant.local`.
/// Every candidate is checked with `GET /api/health` before it's offered.
@Observable
@MainActor
final class Discovery {
    struct Server: Identifiable, Hashable {
        let url: URL
        let version: String?
        var id: String { url.absoluteString }
        var host: String { "\(url.host ?? url.absoluteString):\(url.port ?? Discovery.defaultPort)" }
    }

    /// Ports tried on every host, most likely first.
    nonisolated static let ports = [8091, 8099]
    nonisolated static let defaultPort = 8091

    private(set) var servers: [Server] = []
    private(set) var searching = false
    private var browser: NWBrowser?
    private var tried: Set<String> = []

    func start() {
        stop()
        searching = true
        tried = []
        for host in ["homeassistant.local", "homeassistant"] { probe(host: host) }

        let params = NWParameters.tcp
        params.includePeerToPeer = false
        let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_home-assistant._tcp", domain: nil), using: params)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let hosts = results.flatMap(Self.hosts(in:))
            Task { @MainActor in hosts.forEach { self?.probe(host: $0) } }
        }
        browser.start(queue: .main)
        self.browser = browser
        Task {
            try? await Task.sleep(for: .seconds(8))
            searching = false
        }
    }

    func stop() {
        browser?.cancel()
        browser = nil
        searching = false
    }

    /// Hosts named in Home Assistant's TXT record (`internal_url`, `base_url`, `external_url`).
    nonisolated private static func hosts(in result: NWBrowser.Result) -> [String] {
        guard case .bonjour(let txt) = result.metadata else { return [] }
        return ["internal_url", "base_url", "external_url"].compactMap { key in
            txt[key].flatMap(URL.init(string:))?.host
        }
    }

    /// Check each Moonlight port on `host` (`GET /api/health`) and list the ones that answer.
    func probe(host: String) {
        guard !host.isEmpty, tried.insert(host.lowercased()).inserted else { return }
        let name = host.contains(":") && !host.hasPrefix("[") ? "[\(host)]" : host // bare IPv6
        for port in Self.ports {
            if let url = URL(string: "http://\(name):\(port)") { check(url) }
        }
    }

    private func check(_ url: URL) {
        Task {
            guard let health = try? await APIClient(baseURL: url, token: nil).health(), health.ok else { return }
            if !servers.contains(where: { $0.url == url }) {
                servers.append(Server(url: url, version: health.version))
            }
        }
    }

    /// The Apple TV's own IPv4 address, to prefill the manual address picker with the home network's prefix.
    nonisolated static func localIPv4() -> [Int]? {
        var addrs: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&addrs) == 0, let first = addrs else { return nil }
        defer { freeifaddrs(addrs) }
        var found: [Int]?
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard let sa = ifa.ifa_addr, sa.pointee.sa_family == UInt8(AF_INET) else { continue }
            let name = String(cString: ifa.ifa_name)
            guard name.hasPrefix("en") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(sa, socklen_t(sa.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                let parts = String(cString: host).split(separator: ".").compactMap { Int($0) }
                if parts.count == 4 { found = parts; if name == "en0" { break } }
            }
        }
        return found
    }
}
