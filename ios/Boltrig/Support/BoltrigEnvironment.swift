import Foundation

/// Build-time facts about where this app points and what it links to.
/// The instance a person signs in to can be changed at sign-in (see `InstanceAddress`);
/// these are the defaults and the fixed public links.
enum BoltrigEnvironment {
    /// The hosted Boltrig this build signs in to unless the person picks another instance.
    /// dev.boltrig.ai is the live preview host today; move this to the production host
    /// once app.boltrig.ai serves the product rather than redirecting to the marketing site.
    static let hostedInstanceURL = URL(string: "https://dev.boltrig.ai")!

    /// Public links shown in Settings. These pages do not exist on boltrig.ai yet; the
    /// launch checklist (docs/IOS-LAUNCH-READINESS.md) carries that as a blocker.
    static let privacyPolicyURL = URL(string: "https://boltrig.ai/privacy")!
    static let termsURL = URL(string: "https://boltrig.ai/terms")!
    static let supportURL = URL(string: "https://boltrig.ai")!

    /// How long a phone's access token lives before the person has to sign in again.
    static let accessTokenLifetimeDays = 90

    static var versionLabel: String {
        let info = Bundle.main.infoDictionary ?? [:]
        let version = info["CFBundleShortVersionString"] as? String ?? "0"
        let build = info["CFBundleVersion"] as? String ?? "0"
        return "\(version) (\(build))"
    }
}

/// Parses and persists the address of the Boltrig instance this phone talks to.
/// Only https is accepted: the session cookie and the access token both travel in
/// the clear otherwise, and App Transport Security would refuse the connection anyway.
enum InstanceAddress {
    private static let defaultsKey = "boltrig.instanceURL"

    /// Turns what a person typed into a canonical `https://host[:port]` URL, or nil.
    static func parse(_ text: String) -> URL? {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        if !value.contains("://") { value = "https://" + value }
        guard var components = URLComponents(string: value),
              let host = components.host?.lowercased(), !host.isEmpty,
              components.scheme?.lowercased() == "https" else { return nil }
        components.scheme = "https"
        components.host = host
        components.path = ""
        components.query = nil
        components.fragment = nil
        components.user = nil
        components.password = nil
        return components.url
    }

    static func load(defaults: UserDefaults = .standard) -> URL {
        guard let raw = defaults.string(forKey: defaultsKey), let url = parse(raw) else {
            return BoltrigEnvironment.hostedInstanceURL
        }
        return url
    }

    static func save(_ url: URL?, defaults: UserDefaults = .standard) {
        if let url, url != BoltrigEnvironment.hostedInstanceURL {
            defaults.set(url.absoluteString, forKey: defaultsKey)
        } else {
            defaults.removeObject(forKey: defaultsKey)
        }
    }

    /// A short name for the instance, for labels: "dev.boltrig.ai".
    static func label(for url: URL) -> String {
        guard let host = url.host else { return url.absoluteString }
        if let port = url.port { return "\(host):\(port)" }
        return host
    }
}
