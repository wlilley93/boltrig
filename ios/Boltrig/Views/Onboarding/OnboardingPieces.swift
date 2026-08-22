import SwiftUI

/// The shared look of first-run setup: the same cards, fields and filled button as sign-in,
/// so the flow reads as one ceremony from the first screen to Today.
struct OnboardingCard<Content: View>: View {
    var kicker: String? = nil
    let title: String
    var lead: String? = nil
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                if let kicker {
                    Text(kicker)
                        .font(.footnote.weight(.semibold))
                        .textCase(.uppercase)
                        .foregroundStyle(BoltrigTheme.accent)
                }
                Text(title)
                    .font(.title2.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                if let lead {
                    Text(lead)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            content
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BoltrigTheme.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}

struct OnboardingMessage: View {
    let message: String

    var body: some View {
        Text(message)
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(BoltrigTheme.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
            .accessibilityAddTraits(.isStaticText)
    }
}

struct OnboardingPrimaryButton: View {
    let title: String
    let busy: Bool
    var enabled = true
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if busy { ProgressView().controlSize(.small).tint(BoltrigTheme.onControl) }
                Text(title)
            }
            .foregroundStyle(BoltrigTheme.onControl)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .tint(BoltrigTheme.control)
        .disabled(busy || !enabled)
    }
}

/// A caption above a field: "Your name", "Key (optional)", "Address".
struct OnboardingFieldLabel: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.footnote.weight(.medium))
            .foregroundStyle(.secondary)
    }
}

/// A row that opens a picker: the label, the current value and a chevron.
struct OnboardingPickerLabel: View {
    let value: String
    var placeholder = false

    var body: some View {
        HStack {
            Text(value)
                .foregroundStyle(placeholder ? .secondary : .primary)
                .lineLimit(1)
            Spacer()
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
    }
}

extension View {
    func onboardingField() -> some View {
        self
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(BoltrigTheme.cardSecondary, in: RoundedRectangle(cornerRadius: 12))
    }
}
