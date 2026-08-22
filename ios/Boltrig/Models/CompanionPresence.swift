import Foundation

/// What the phone shows for the account's companion. Boltrig for iPhone ships Familiar only;
/// an account whose stored id is anything else is switched to Familiar the first time the phone
/// loads it (see `SessionStore.adoptFamiliarIfNeeded`). The stored id itself is never displayed.
enum CompanionPresence: Equatable {
    case familiar
    case unset
    case other

    static let familiarID = "familiar"

    init(characterID: String?) {
        guard let characterID, !characterID.isEmpty else {
            self = .unset
            return
        }
        self = characterID == Self.familiarID ? .familiar : .other
    }

    /// True when the account must be switched to Familiar before the phone shows a companion.
    var needsAdoption: Bool { self != .familiar }
}
