import Combine
import Foundation

/// First-run setup on the phone: Name, Provider, Image model (optional), Ready. Familiar is
/// the only companion here, so there is no companion step and no voice step. Finishing writes
/// the name, then the settings the web app writes, then tells Familiar she was chosen.
@MainActor
final class OnboardingStore: ObservableObject {
    enum Step: Int, CaseIterable, Equatable {
        case name, provider, vision, ready
    }

    enum Copy {
        static let nameInvalid = "Use 1 to 80 ordinary characters."
        static let saveFailed = "Setup could not be saved. Try again."
    }

    static let stepCount = Step.allCases.count

    /// The settings the web app writes when setup completes; the phone writes the same two.
    static let completedSettings: [String: Any] = [
        "agent.character": CompanionPresence.familiarID,
        "setup.onboarding_version": 1,
    ]

    @Published private(set) var step: Step
    @Published var name: String
    @Published var nameMessage: String?
    @Published var finishMessage: String?
    @Published private(set) var isFinishing = false

    let text: ProviderSetupStore
    let vision: ProviderSetupStore
    /// Called when the person presses Start on the Ready step; the owner re-reads the account.
    var onFinished: (() -> Void)?

    private let client: BoltrigClient
    private let account: Account
    private var finishInFlight = false
    private var forwarding: Set<AnyCancellable> = []

    init(client: BoltrigClient, account: Account, catalogue: ProviderCatalogue? = nil) {
        self.client = client
        self.account = account
        self.name = account.displayName
        self.step = Self.startStep(for: account)
        self.text = ProviderSetupStore(client: client, account: account, modality: .text, catalogue: catalogue)
        self.vision = ProviderSetupStore(client: client, account: account, modality: .vision, catalogue: catalogue)
        for child in [text, vision] {
            child.objectWillChange
                .sink { [weak self] _ in self?.objectWillChange.send() }
                .store(in: &forwarding)
        }
    }

    #if DEBUG
    /// Simulator captures only: land on a step with a name already given.
    func debugJump(to target: Step, name: String) {
        self.name = name
        step = target
    }
    #endif

    /// An account that already has a name (set on the web) starts at Provider.
    static func startStep(for account: Account) -> Step {
        account.displayName.isEmpty ? .name : .provider
    }

    var stepNumber: Int { step.rawValue + 1 }

    var isBusy: Bool { isFinishing || text.busy || vision.busy }

    var canGoBack: Bool { (step == .provider || step == .vision) && !isBusy }

    var canContinue: Bool {
        if isBusy { return false }
        switch step {
        case .name:
            return !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .provider, .vision, .ready:
            return true
        }
    }

    var primaryLabel: String {
        if isFinishing { return "Finishing" }
        if text.busy || vision.busy { return "Connecting" }
        return step == .ready ? "Start" : "Continue"
    }

    // MARK: Moving through the steps

    func back() {
        guard canGoBack, let previous = Step(rawValue: step.rawValue - 1) else { return }
        finishMessage = nil
        step = previous
    }

    /// What the one forward button does on each step.
    func continueFlow() async {
        guard canContinue else { return }
        switch step {
        case .name:
            guard let valid = Self.normalizedName(name) else {
                nameMessage = Copy.nameInvalid
                return
            }
            name = valid
            nameMessage = nil
            step = .provider
        case .provider:
            if await text.complete() { step = .vision }
        case .vision:
            if await vision.complete() { _ = await finish() }
        case .ready:
            onFinished?()
        }
    }

    /// Skipping the image model submits nothing and finishes setup.
    func skipVision() async {
        guard step == .vision, !isBusy else { return }
        _ = await finish()
    }

    /// Name first, then the two settings, in that order, once: a second press while the first
    /// is in flight does nothing. Telling Familiar is best effort.
    func finish() async -> Bool {
        guard !finishInFlight else { return false }
        guard let displayName = Self.normalizedName(name) else {
            nameMessage = Copy.nameInvalid
            step = .name
            return false
        }
        finishInFlight = true
        isFinishing = true
        finishMessage = nil
        defer {
            finishInFlight = false
            isFinishing = false
        }
        do {
            try await client.updateProfile(displayName: displayName)
            try await client.putSettings(Self.completedSettings)
            try? await client.announceAdopted(character: CompanionPresence.familiarID)
            step = .ready
            return true
        } catch let error as BoltrigError {
            if case let .rejected(reason) = error.kind, reason == BoltrigError.displayNameReason {
                // The server would not keep the name: take the person to where the fix is.
                nameMessage = BoltrigError.plainCopy(for: reason)
                step = .name
            } else {
                finishMessage = Copy.saveFailed
            }
            return false
        } catch {
            finishMessage = Copy.saveFailed
            return false
        }
    }

    // MARK: Name rule

    /// The server's rule, applied before sending: whitespace collapsed to single spaces,
    /// 1 to 80 characters, nothing invisible. Nil when the name would be refused.
    static func normalizedName(_ raw: String) -> String? {
        let collapsed = raw
            .split(whereSeparator: { $0.isWhitespace || $0.isNewline })
            .joined(separator: " ")
        let length = collapsed.unicodeScalars.count
        guard (1...80).contains(length) else { return nil }
        let hasControl = collapsed.unicodeScalars.contains { scalar in
            switch scalar.properties.generalCategory {
            case .control, .format, .surrogate:
                return true
            default:
                return false
            }
        }
        return hasControl ? nil : collapsed
    }
}
