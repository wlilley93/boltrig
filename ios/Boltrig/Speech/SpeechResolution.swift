import Foundation

/// Whether, through which provider, and in which voice a finished reply is read aloud.
/// Mirrors the web: the setting turns it on, the server's bound voice provider decides the
/// route, the person's override (local voices only) or Familiar's own voice decides the voice.
/// Nothing here invents a default voice; no voice means silence.
struct SpeechResolution: Equatable {
    static let speakVerb = "voice.speak"
    static let overrideProvider = "pocket-voice"
    static let familiarID = "familiar"
    /// Familiar's fallback voices per provider, from the bundle the web ships.
    static let familiarFallbackVoices: [String: String] = [
        "pocket-voice": "familiar",
        "fish": "c8f64deb39914cfca7f47ccfc3bca82f",
    ]
    static let maxSpokenCharacters = 15_000

    let enabled: Bool
    let provider: String?
    let voiceID: String?

    static let silent = SpeechResolution(enabled: false, provider: nil, voiceID: nil)

    var canSpeak: Bool { enabled && provider != nil && voiceID != nil }

    static func resolve(account: Account, capabilities: CapabilitiesSnapshot?) -> SpeechResolution {
        let provider = capabilities?.provider(for: speakVerb)
        var voice: String? = nil
        if let provider {
            if provider == overrideProvider, let override = account.voiceOverrides[familiarID], isValidVoiceID(override) {
                voice = override
            } else {
                voice = familiarFallbackVoices[provider]
            }
        }
        return SpeechResolution(enabled: account.readReplies, provider: provider, voiceID: voice)
    }

    static func isValidVoiceID(_ value: String) -> Bool {
        value.range(of: "^[a-z0-9][a-z0-9._-]{0,63}$", options: [.regularExpression, .caseInsensitive]) != nil
    }

    /// The text that is spoken: markdown reduced the way the web reduces it, capped.
    static func speechText(_ markdown: String) -> String {
        var text = markdown
        let rules: [(String, String, NSRegularExpression.Options)] = [
            ("```[\\s\\S]*?```", " Code omitted. ", []),
            ("!\\[([^\\]]*)\\]\\([^)]*\\)", "$1", []),
            ("\\[([^\\]]+)\\]\\([^)]*\\)", "$1", []),
            ("`([^`]+)`", "$1", []),
            ("(\\*\\*|__)(.*?)\\1", "$2", []),
            ("(^|[^\\w])([*_])([^*_]+)\\2", "$1$3", []),
            ("^\\s{0,3}#{1,6}\\s+", "", [.anchorsMatchLines]),
            ("^\\s{0,3}>\\s?", "", [.anchorsMatchLines]),
            ("^\\s{0,3}[-*+]\\s+", "", [.anchorsMatchLines]),
            ("\\s+", " ", []),
        ]
        for (pattern, replacement, options) in rules {
            guard let regex = try? NSRegularExpression(pattern: pattern, options: options) else { continue }
            text = regex.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text), withTemplate: replacement)
        }
        text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return String(text.prefix(maxSpokenCharacters))
    }
}
