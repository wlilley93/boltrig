import Foundation

/// Where the signed-in session is kept between launches.
protocol SessionVault {
    func load() throws -> StoredSession?
    func save(_ session: StoredSession) throws
    func clear() throws
}

/// The real one: a single Keychain item holding the stored session as JSON.
struct KeychainSessionVault: SessionVault {
    let account: String

    init(account: String = "session") {
        self.account = account
    }

    func load() throws -> StoredSession? {
        guard let data = try Keychain.data(for: account) else { return nil }
        return try? JSONDecoder().decode(StoredSession.self, from: data)
    }

    func save(_ session: StoredSession) throws {
        let data = try JSONEncoder().encode(session)
        try Keychain.set(data, for: account)
    }

    func clear() throws {
        try Keychain.remove(account)
    }
}

/// For tests and previews: nothing touches the Keychain.
final class InMemorySessionVault: SessionVault {
    var stored: StoredSession?

    init(stored: StoredSession? = nil) {
        self.stored = stored
    }

    func load() throws -> StoredSession? { stored }
    func save(_ session: StoredSession) throws { stored = session }
    func clear() throws { stored = nil }
}
