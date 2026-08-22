import Foundation

/// The person the server says just signed in. Comes back from sign-in and the
/// two-step challenge; the fuller profile is read separately from the account route.
struct SignedInUser: Equatable, Decodable {
    let id: String
    let email: String
    let role: String
}

/// What a sign-in attempt resolved to. The server issues a session for the first three
/// and no session at all for the fourth (the code has to be supplied first).
enum SignInOutcome: Equatable {
    case signedIn(csrfToken: String, user: SignedInUser)
    case passwordChangeRequired(csrfToken: String, user: SignedInUser)
    case twoFactorEnrolmentRequired(csrfToken: String, user: SignedInUser)
    case twoFactorRequired(challengeToken: String)
}

/// Returned once when two-step verification is being set up. The recovery codes are
/// shown to the person exactly once and never stored by the app.
struct TwoFactorEnrolment: Equatable, Decodable {
    let otpauthURI: String
    let secret: String
    let recoveryCodes: [String]

    enum CodingKeys: String, CodingKey {
        case otpauthURI = "otpauth_uri"
        case secret
        case recoveryCodes = "recovery_codes"
    }
}

/// A personal access token minted for this phone. The secret is returned once.
struct MintedAccessToken: Equatable {
    let id: String
    let secret: String
}

/// The signed-in account as the server describes it, read from the account route.
struct Account: Equatable {
    let id: String
    let email: String
    let displayName: String
    let role: String
    let activeWorkspaceID: String?
    /// The web app's first-run flow has been completed for this account.
    let onboardingComplete: Bool
    /// The companion id stored on the account, or nil when none is set yet. The phone
    /// never displays an id: see `CompanionPresence`.
    let characterID: String?

    var nameForDisplay: String {
        displayName.isEmpty ? email : displayName
    }

    var initials: String {
        let source = displayName.isEmpty ? String(email.prefix(while: { $0 != "@" })) : displayName
        let parts = source.split(whereSeparator: { $0 == " " || $0 == "." || $0 == "_" || $0 == "-" })
        let letters = parts.prefix(2).compactMap { $0.first }
        if letters.isEmpty { return String(source.prefix(2)).uppercased() }
        return String(letters).uppercased()
    }

    var companionPresence: CompanionPresence {
        CompanionPresence(characterID: characterID)
    }

    /// Decodes the `/v1/me/settings` body: profile, active workspace and a settings bag
    /// whose values are strings, numbers and booleans mixed together.
    static func decode(_ data: Data) throws -> Account {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let profile = root["profile"] as? [String: Any],
              let id = profile["id"] as? String,
              let email = profile["email"] as? String else {
            throw BoltrigError(kind: .invalidResponse, status: 200)
        }
        let settings = root["settings"] as? [String: Any] ?? [:]
        let onboardingVersion: Int = {
            if let value = settings["setup.onboarding_version"] as? Int { return value }
            if let value = settings["setup.onboarding_version"] as? Double { return Int(value) }
            if let value = settings["setup.onboarding_version"] as? String { return Int(value) ?? 0 }
            return 0
        }()
        return Account(
            id: id,
            email: email,
            displayName: (profile["display_name"] as? String ?? "").trimmingCharacters(in: .whitespaces),
            role: profile["role"] as? String ?? "",
            activeWorkspaceID: root["active_workspace_id"] as? String,
            onboardingComplete: onboardingVersion >= 1,
            characterID: (settings["agent.character"] as? String).flatMap { value in
                let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                return trimmed.isEmpty ? nil : trimmed
            }
        )
    }
}

/// What the phone keeps between launches: which instance, which token, and the token
/// itself. Lives in the Keychain, never in UserDefaults.
struct StoredSession: Codable, Equatable {
    let instanceURL: URL
    let tokenID: String
    let secret: String
    let createdAt: Date
}
