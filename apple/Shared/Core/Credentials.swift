import Foundation
import Security

/// Where Moonlight lives and this device's display token. The token goes in the Keychain, the addresses in defaults.
enum Credentials {
    private static let serverKey = "moonlight.server"
    private static let remoteKey = "moonlight.remote"
    private static let account = "display-token"
    private static let service = "Moonlight"

    static var server: URL? {
        get { UserDefaults.standard.string(forKey: serverKey).flatMap(URL.init(string:)) }
        set { UserDefaults.standard.set(newValue?.absoluteString, forKey: serverKey) }
    }

    /// The add-on's public https address (its `external_url`), used when the home address doesn't answer.
    static var remote: URL? {
        get { UserDefaults.standard.string(forKey: remoteKey).flatMap(URL.init(string:)) }
        set { UserDefaults.standard.set(newValue?.absoluteString, forKey: remoteKey) }
    }

    /// The address to use right now: home first, then the public one; the home one if neither answers.
    static func reachableServer() async -> URL? {
        guard let home = server else { return nil }
        guard let remote, remote != home else { return home }
        if await APIClient.answers(home, timeout: 3) { return home }
        if await APIClient.answers(remote, timeout: 8) { return remote }
        return home
    }

    static var token: String? {
        get {
            var query = baseQuery
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitOne
            var out: CFTypeRef?
            guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
            return String(data: data, encoding: .utf8)
        }
        set {
            SecItemDelete(baseQuery as CFDictionary)
            guard let newValue, let data = newValue.data(using: .utf8) else { return }
            var query = baseQuery
            query[kSecValueData as String] = data
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    private static var baseQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }
}
