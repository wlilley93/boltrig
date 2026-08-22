import SwiftUI

struct MessageBubble: View {
    let role: ChatMessage.Role
    let text: String

    var body: some View {
        HStack {
            if role == .user { Spacer(minLength: 42) }
            Text(text)
                .font(.body)
                .foregroundStyle(role == .user ? BoltrigTheme.onControl : Color.primary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 15)
                .padding(.vertical, 12)
                .background(role == .user ? BoltrigTheme.control : BoltrigTheme.card,
                            in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .textSelection(.enabled)
            if role == .assistant { Spacer(minLength: 42) }
        }
    }
}

/// A line of what Boltrig did during the turn: a tool used, a file made, a helper started.
struct ReceiptLine: View {
    let text: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "circle.fill").font(.system(size: 5)).foregroundStyle(.tertiary)
            Text(text).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
        }
        .padding(.leading, 6)
    }
}

/// Boltrig is asking the person something mid-turn.
struct QuestionCard: View {
    let question: ChatSession.PendingQuestion
    let onAnswer: (String) -> Void
    @State private var answer = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "questionmark.bubble.fill").foregroundStyle(BoltrigTheme.accent)
                Text("Boltrig has a question").font(.subheadline.weight(.semibold))
            }
            Text(question.prompt).font(.body).fixedSize(horizontal: false, vertical: true)
            if !question.choices.isEmpty {
                FlowChoices(choices: question.choices) { choice in onAnswer(choice) }
            }
            HStack(spacing: 8) {
                TextField("Your answer", text: $answer)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .background(BoltrigTheme.cardSecondary, in: RoundedRectangle(cornerRadius: 12))
                    .onSubmit(send)
                Button("Send answer", action: send)
                    .buttonStyle(.borderedProminent)
                    .tint(BoltrigTheme.control)
                    .foregroundStyle(BoltrigTheme.onControl)
                    .disabled(answer.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(16)
        .background(BoltrigTheme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private func send() {
        let value = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        answer = ""
        onAnswer(value)
    }
}

private struct FlowChoices: View {
    let choices: [String]
    let onPick: (String) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(choices, id: \.self) { choice in
                    Button(choice) { onPick(choice) }
                        .buttonStyle(.bordered)
                        .tint(.primary)
                }
            }
        }
    }
}

struct AttachmentChip: View {
    let name: String
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "doc").font(.footnote)
            Text(name).font(.footnote).lineLimit(1)
            Button(action: onRemove) { Image(systemName: "xmark.circle.fill").font(.footnote) }
                .buttonStyle(.plain)
                .accessibilityLabel("Remove \(name)")
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(BoltrigTheme.cardSecondary, in: Capsule())
    }
}
