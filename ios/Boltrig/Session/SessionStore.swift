import Foundation
import Combine
import UIKit

/// Owns who is signed in, on which instance, and with what credential.
///
/// Signing in is a short ceremony on a cookie session (email and password, then the
/// two-step code, a forced password change or two-step setup when the server asks),
/// at the end of which the app mints a personal access token for this phone, keeps
/// only that token in the Keychain, and closes the cookie session. Every later request
/// carries the token; a 401 means it has expired or been revoked and the person signs in again.
@MainActor
final class SessionStore: ObservableObject {
    enum State: Equatable {
        case restoring
        case signedOut
        case signingIn
        case twoFactor(challengeToken: String)
        case passwordChange(csrfToken: String)
        case twoFactorEnrolment(csrfToken: String, enrolment: TwoFactorEnrolment?)
        case recoveryCodes(csrfToken: String, codes: [String])
        case unreachable
        case signedIn(Account)
    }

    @Published private(set) var state: State = .restoring
    @Published var errorMessage: String?
    @Published private(set) var instanceURL: URL
    @Published var isBusy = false

    private let vault: SessionVault
    private let configuration: URLSessionConfiguration
    private let defaults: UserDefaults
    private var signInSession: URLSession?
    private var tokenSession: URLSession?

    init(vault: SessionVault = KeychainSessionVault(),
         configuration: URLSessionConfiguration = .ephemeral,
         defaults: UserDefaults = .standard) {
        self.vault = vault
        self.configuration = configuration
        self.defaults = defaults
        self.instanceURL = InstanceAddress.load(defaults: defaults)
    }

    /// The client the rest of the app uses once signed in.
    var apiClient: BoltrigClient? {
        guard case .signedIn = state, let stored = try? vault.load() else { return nil }
        return tokenClient(stored.secret)
    }

    var account: Account? {
        if case let .signedIn(account) = state { return account }
        return nil
    }

    var instanceLabel: String { InstanceAddress.label(for: instanceURL) }
    var isHostedInstance: Bool { instanceURL == BoltrigEnvironment.hostedInstanceURL }

    // MARK: Launch

    func restore() async {
        errorMessage = nil
        guard let stored = try? vault.load() else {
            state = .signedOut
            return
        }
        guard stored.instanceURL == instanceURL else {
            try? vault.clear()
            state = .signedOut
            return
        }
        state = .restoring
        do {
            let account = try await tokenClient(stored.secret).account()
            state = .signedIn(account)
        } catch let error as BoltrigError {
            switch error.kind {
            case .unauthenticated, .forbidden:
                try? vault.clear()
                state = .signedOut
            case .unreachable, .server:
                state = .unreachable
            default:
                try? vault.clear()
                state = .signedOut
                errorMessage = error.errorDescription
            }
        } catch {
            state = .unreachable
        }
    }

    func refreshAccount() async {
        guard let client = apiClient, let refreshed = try? await client.account() else { return }
        state = .signedIn(refreshed)
    }

    // MARK: Sign-in ceremony

    func signIn(email: String, password: String) async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedEmail.isEmpty, !password.isEmpty else {
            errorMessage = "Enter your email and password."
            return
        }
        await run {
            self.state = .signingIn
            let session = URLSession(configuration: self.configuration)
            self.signInSession = session
            let outcome = try await self.sessionClient(.none, session: session)
                .login(email: trimmedEmail, password: password)
            await self.route(outcome)
        } onFailure: {
            self.state = .signedOut
        }
    }

    func submitTwoFactorCode(_ code: String) async {
        guard case let .twoFactor(challengeToken) = state, let session = signInSession else { return }
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "Enter the code from your authenticator app."
            return
        }
        await run {
            let outcome = try await self.sessionClient(.none, session: session)
                .completeTwoFactor(challengeToken: challengeToken, code: trimmed)
            await self.route(outcome)
        }
    }

    func changePassword(current: String, new: String, confirmation: String) async {
        guard case let .passwordChange(csrfToken) = state, let session = signInSession else { return }
        guard new.count >= 12 else {
            errorMessage = "Choose a new password of at least 12 characters."
            return
        }
        guard new == confirmation else {
            errorMessage = "The two new passwords do not match."
            return
        }
        await run {
            try await self.sessionClient(.session(csrfToken: csrfToken), session: session)
                .changePassword(current: current, new: new)
            await self.finishSignIn(csrfToken: csrfToken)
        }
    }

    func beginTwoFactorEnrolment() async {
        guard case let .twoFactorEnrolment(csrfToken, existing) = state, existing == nil,
              let session = signInSession else { return }
        await run {
            let enrolment = try await self.sessionClient(.session(csrfToken: csrfToken), session: session)
                .beginTwoFactorEnrolment()
            self.state = .twoFactorEnrolment(csrfToken: csrfToken, enrolment: enrolment)
        }
    }

    func verifyTwoFactorEnrolment(code: String) async {
        guard case let .twoFactorEnrolment(csrfToken, enrolment) = state, let enrolment,
              let session = signInSession else { return }
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "Enter the six-digit code your authenticator app shows."
            return
        }
        await run {
            _ = try await self.sessionClient(.session(csrfToken: csrfToken), session: session)
                .verifyTwoFactorEnrolment(code: trimmed)
            self.state = .recoveryCodes(csrfToken: csrfToken, codes: enrolment.recoveryCodes)
        }
    }

    func acknowledgeRecoveryCodes() async {
        guard case let .recoveryCodes(csrfToken, _) = state else { return }
        await run {
            await self.finishSignIn(csrfToken: csrfToken)
        }
    }

    func requestPasswordReset(email: String) async {
        let trimmed = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "Enter the email you sign in with first."
            return
        }
        await run {
            try await self.sessionClient(.none, session: URLSession(configuration: self.configuration))
                .requestPasswordReset(email: trimmed)
            self.errorMessage = "If that account can be recovered, reset instructions are on their way to \(trimmed)."
        }
    }

    /// Abandons a half-finished sign-in and returns to the sign-in form.
    func cancelSignIn() {
        signInSession = nil
        errorMessage = nil
        state = .signedOut
    }

    func signOut() async {
        isBusy = true
        defer { isBusy = false }
        if let stored = try? vault.load() {
            try? await tokenClient(stored.secret).revokeAccessToken(id: stored.tokenID)
        }
        try? vault.clear()
        signInSession = nil
        errorMessage = nil
        state = .signedOut
    }

    /// Points the app at another Boltrig. Signs out first if needed: a token belongs to one instance.
    func useInstance(_ url: URL) async {
        if url == instanceURL { return }
        if case .signedIn = state { await signOut() }
        try? vault.clear()
        instanceURL = url
        InstanceAddress.save(url, defaults: defaults)
        errorMessage = nil
        state = .signedOut
    }

    func retryRestore() async {
        await restore()
    }

    // MARK: Internals

    private func route(_ outcome: SignInOutcome) async {
        switch outcome {
        case let .twoFactorRequired(challengeToken):
            state = .twoFactor(challengeToken: challengeToken)
        case let .passwordChangeRequired(csrfToken, _):
            state = .passwordChange(csrfToken: csrfToken)
        case let .twoFactorEnrolmentRequired(csrfToken, _):
            state = .twoFactorEnrolment(csrfToken: csrfToken, enrolment: nil)
        case let .signedIn(csrfToken, _):
            await finishSignIn(csrfToken: csrfToken)
        }
    }

    /// Mints this phone's token on the cookie session, stores it, closes the cookie session,
    /// and loads the account. A clamp the server still holds routes back into the ceremony.
    private func finishSignIn(csrfToken: String) async {
        guard let session = signInSession else {
            state = .signedOut
            return
        }
        let sessionClient = sessionClient(.session(csrfToken: csrfToken), session: session)
        do {
            let minted = try await sessionClient.mintAccessToken(name: Self.tokenName(), ttlDays: BoltrigEnvironment.accessTokenLifetimeDays)
            let stored = StoredSession(instanceURL: instanceURL, tokenID: minted.id, secret: minted.secret, createdAt: Date())
            try vault.save(stored)
            try? await sessionClient.logout()
            signInSession = nil
            let account = try await tokenClient(minted.secret).account()
            state = .signedIn(account)
        } catch let error as BoltrigError {
            switch error.kind {
            case .passwordChangeRequired:
                state = .passwordChange(csrfToken: csrfToken)
            case .twoFactorEnrolmentRequired:
                state = .twoFactorEnrolment(csrfToken: csrfToken, enrolment: nil)
            default:
                try? vault.clear()
                state = .signedOut
                errorMessage = error.errorDescription
            }
        } catch {
            try? vault.clear()
            state = .signedOut
            errorMessage = BoltrigError(kind: .unreachable, status: 0).errorDescription
        }
    }

    private func run(_ work: @escaping () async throws -> Void, onFailure: (() -> Void)? = nil) async {
        errorMessage = nil
        isBusy = true
        defer { isBusy = false }
        do {
            try await work()
        } catch let error as BoltrigError {
            errorMessage = error.errorDescription
            onFailure?()
        } catch {
            errorMessage = BoltrigError(kind: .unreachable, status: 0).errorDescription
            onFailure?()
        }
    }

    private func sessionClient(_ authorization: Authorization, session: URLSession) -> BoltrigClient {
        BoltrigClient(baseURL: instanceURL, authorization: authorization, session: session)
    }

    private func tokenClient(_ secret: String) -> BoltrigClient {
        if tokenSession == nil {
            let config = configuration.copy() as? URLSessionConfiguration ?? .ephemeral
            config.httpShouldSetCookies = false
            config.httpCookieAcceptPolicy = .never
            tokenSession = URLSession(configuration: config)
        }
        return BoltrigClient(baseURL: instanceURL, authorization: .accessToken(secret), session: tokenSession!)
    }

    /// The name the token shows under in the web app's token list, so a person can
    /// recognise and revoke this phone from elsewhere.
    static func tokenName(now: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return "\(UIDevice.current.model) app, signed in \(formatter.string(from: now))"
    }
}
