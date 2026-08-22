import Foundation

/// Every failure the client surfaces, already reduced to something the person can act on.
struct BoltrigError: Error, Equatable {
    enum Kind: Equatable {
        /// No answer from the network at all.
        case unreachable
        /// 401: no session, expired token, revoked token.
        case unauthenticated
        /// 403 carrying the forced password rotation clamp.
        case passwordChangeRequired
        /// 403 carrying the two-step enrolment clamp.
        case twoFactorEnrolmentRequired
        /// Any other 403.
        case forbidden
        /// 429 from the fixed-window limiters.
        case throttled
        /// Another 4xx whose body carried a reason.
        case rejected(reason: String)
        /// 5xx, or a 2xx whose body could not be read. `reason` is the server's own
        /// sentence when the body carried one (a 503 from provider setup says what to do).
        case server(status: Int, reason: String? = nil)
        case invalidResponse
    }

    let kind: Kind
    let status: Int
}

extension BoltrigError: LocalizedError {
    var errorDescription: String? {
        switch kind {
        case .unreachable:
            return "Boltrig could not be reached. Check your connection and try again."
        case .unauthenticated:
            return "Sign in to Boltrig to continue."
        case .passwordChangeRequired:
            return "Choose a new password to continue."
        case .twoFactorEnrolmentRequired:
            return "Set up two-step verification to continue."
        case .forbidden:
            return "This workspace does not allow that."
        case .throttled:
            return "Too many attempts. Wait a minute and try again."
        case let .rejected(reason):
            return BoltrigError.plainCopy(for: reason)
        case let .server(status, _):
            return "Boltrig had a problem (HTTP \(status)). Try again in a moment."
        case .invalidResponse:
            return "Boltrig returned something this app could not read."
        }
    }

    /// The reason the profile route gives for a name it will not keep.
    static let displayNameReason = "display_name must be 1-80 safe characters"

    /// The server's reasons are short and mostly plain; the ones a person meets while
    /// signing in get a friendlier sentence, the rest are shown as written.
    static func plainCopy(for reason: String) -> String {
        switch reason {
        case "invalid email or password":
            return "That email and password did not match."
        case "invalid or expired code":
            return "That code was not accepted. Check the time on your phone and try the current code."
        case "invalid or expired invite":
            return "That invitation is no longer valid. Ask for a new one."
        case "invalid or expired reset token":
            return "That reset link has expired. Request a new one."
        case "the new password must differ":
            return "Choose a password you have not used before."
        case "two-factor is already enabled":
            return "Two-step verification is already on for this account."
        case "two-factor is not enabled":
            return "Two-step verification is not on for this account."
        case "not_found":
            return "That could not be found."
        case displayNameReason:
            return "Your name must be 1 to 80 ordinary characters."
        case "":
            return "Boltrig could not complete that."
        default:
            let first = reason.prefix(1).uppercased()
            let rest = String(reason.dropFirst())
            return first + rest + (reason.hasSuffix(".") ? "" : ".")
        }
    }
}
