import Foundation

enum AppTab: Hashable {
    case today
    case chat
    case settings
}

/// One row of `GET /v1/conversations`. `working` is the server's own answer to
/// "is a run active here"; the app never infers it from the title or status text.
struct ConversationSummary: Identifiable, Codable, Hashable {
    let id: String
    var title: String
    var status: String
    var updatedAt: String
    var working: Bool?
    var companionID: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case status
        case updatedAt = "updated_at"
        case working
        case companionID = "companion_id"
    }

    var isWorking: Bool { working ?? false }
}

/// One pending item from `GET /v1/hitl`: an approval, a clarifying question,
/// an escalation or a plain question.
struct ApprovalRequest: Identifiable, Codable, Hashable {
    let id: String
    var type: String
    var question: String
    var verb: String?
    var urgency: String?
    var options: [String]?
    var runID: String?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case question
        case verb
        case urgency
        case options
        case runID = "run_id"
    }

    /// Plain heading for the card: the verb when the server names one, otherwise the kind.
    var heading: String {
        if let verb, !verb.isEmpty { return verb }
        switch type {
        case "question", "clarification": return "A question for you"
        case "escalation": return "Needs your call"
        default: return "A decision"
        }
    }
}

struct ChatMessage: Identifiable, Hashable {
    enum Role: String {
        case user
        case assistant
    }

    let id: UUID
    let role: Role
    var content: String
    let createdAt: Date

    init(id: UUID = UUID(), role: Role, content: String, createdAt: Date) {
        self.id = id
        self.role = role
        self.content = content
        self.createdAt = createdAt
    }
}

struct SettingItem: Identifiable, Hashable {
    let id: String
    let label: String
    let title: String
    let lead: String
}

extension SettingItem {
    /// The sections the web app offers. Each opens on the web for now; the rows are
    /// honest about that rather than showing placeholder values.
    static let all: [SettingItem] = [
        SettingItem(id: "you", label: "You", title: "You", lead: "How Boltrig looks, speaks and reaches you."),
        SettingItem(id: "behaviour", label: "Behaviour", title: "Behaviour", lead: "What Boltrig may notice, remember, and do while you are away."),
        SettingItem(id: "autonomy", label: "Autonomy", title: "Autonomy", lead: "Approval rules and spending limits that can stop work."),
        SettingItem(id: "spend", label: "Spending", title: "Spending", lead: "What work is allowed to cost, and what it has cost."),
        SettingItem(id: "models", label: "Models", title: "Models", lead: "Choose the models Boltrig uses."),
        SettingItem(id: "health", label: "Health", title: "Health", lead: "What is working, and what Boltrig cannot do yet."),
        SettingItem(id: "organisation", label: "Organisation", title: "Organisation", lead: "People, keys and the record. Admin-only."),
        SettingItem(id: "archived", label: "Archived chats", title: "Archived chats", lead: "Out of the way, not gone. Everything they did is still in the record."),
    ]
}

extension String {
    var relativeAge: String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = formatter.date(from: self)
        if date == nil {
            formatter.formatOptions = [.withInternetDateTime]
            date = formatter.date(from: self)
        }
        guard let date else { return "" }
        let seconds = max(0, Int(Date().timeIntervalSince(date)))
        if seconds < 60 { return "now" }
        let minutes = Int(round(Double(seconds) / 60))
        if minutes < 60 { return "\(minutes)m" }
        let hours = Int(round(Double(minutes) / 60))
        if hours < 24 { return "\(hours)h" }
        return "\(Int(round(Double(hours) / 24)))d"
    }
}

#if DEBUG
extension ConversationSummary {
    static let preview: [ConversationSummary] = [
        ConversationSummary(id: "preview-working", title: "Prepare the morning briefing", status: "Working now",
                            updatedAt: ISO8601DateFormatter().string(from: Date().addingTimeInterval(-240)), working: true),
        ConversationSummary(id: "preview-contract", title: "Review the vendor contract", status: "Complete",
                            updatedAt: ISO8601DateFormatter().string(from: Date().addingTimeInterval(-3600)), working: false),
        ConversationSummary(id: "preview-travel", title: "Find options for next week's trip", status: "Complete",
                            updatedAt: ISO8601DateFormatter().string(from: Date().addingTimeInterval(-86_400)), working: false),
    ]
}

extension ApprovalRequest {
    static let preview: [ApprovalRequest] = [
        ApprovalRequest(id: "preview-approval", type: "approval",
                        question: "Create a 30-minute focus block tomorrow at 09:00?", verb: "calendar.event.create"),
    ]
}

extension ChatMessage {
    static let preview: [ChatMessage] = [
        ChatMessage(role: .assistant,
                    content: "Good morning. I can keep work moving, ask when a decision is yours, and leave a clear record of what happened.",
                    createdAt: Date().addingTimeInterval(-120)),
        ChatMessage(role: .user, content: "What are you working on?", createdAt: Date().addingTimeInterval(-90)),
        ChatMessage(role: .assistant,
                    content: "I am preparing your morning briefing and waiting for one calendar decision. You can approve it from Today when you are ready.",
                    createdAt: Date().addingTimeInterval(-60)),
    ]
}

extension Account {
    static let preview = Account(id: "preview", email: "preview@example.com", displayName: "Preview Person", role: "member",
                                 activeWorkspaceID: nil, onboardingComplete: true, characterID: "familiar")
}
#endif
