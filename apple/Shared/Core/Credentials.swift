import Foundation
import Security
#if os(iOS)
import WidgetKit
#endif

/// Where Moonlight lives and this device's display token. The token goes in the Keychain, the addresses in defaults
/// and the Keychain too: the iPhone's home screen widget reads all three from the Keychain (it shares the app's
/// keychain group, which a free Apple ID can sign, unlike an app group).
enum Credentials {
    private static let serverKey = "moonlight.server"
    private static let remoteKey = "moonlight.remote"
    private static let account = "display-token"
    private static let service = "Moonlight"

    static var server: URL? {
        get { (UserDefaults.standard.string(forKey: serverKey) ?? keychain(serverKey)).flatMap(URL.init(string:)) }
        set {
            UserDefaults.standard.set(newValue?.absoluteString, forKey: serverKey)
            setKeychain(serverKey, newValue?.absoluteString)
        }
    }

    /// The add-on's public https address (its `external_url`), used when the home address doesn't answer.
    static var remote: URL? {
        get { (UserDefaults.standard.string(forKey: remoteKey) ?? keychain(remoteKey)).flatMap(URL.init(string:)) }
        set {
            UserDefaults.standard.set(newValue?.absoluteString, forKey: remoteKey)
            setKeychain(remoteKey, newValue?.absoluteString)
        }
    }

    /// Copies addresses saved before the widget existed into the Keychain, and has the widget redraw.
    static func shareWithWidget() {
        for key in [serverKey, remoteKey] {
            let saved = UserDefaults.standard.string(forKey: key)
            if keychain(key) != saved { setKeychain(key, saved) }
        }
        #if os(iOS)
        WidgetCenter.shared.reloadAllTimelines()
        #endif
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
        get { keychain(account) }
        set { setKeychain(account, newValue) }
    }

    private static func keychain(_ account: String) -> String? {
        var query = baseQuery(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func setKeychain(_ account: String, _ value: String?) {
        SecItemDelete(baseQuery(account) as CFDictionary)
        guard let value, let data = value.data(using: .utf8) else { return }
        var query = baseQuery(account)
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(query as CFDictionary, nil)
    }

    private static func baseQuery(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }
}
