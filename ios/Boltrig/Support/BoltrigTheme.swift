import SwiftUI

enum BoltrigTheme {
    /// The accent comes from the asset catalog: the brand core cyan (assets/brand) in dark
    /// mode, a darker teal of the same hue in light mode so links and icons stay readable on white.
    static let accent = Color.accentColor
    /// Filled controls use the system primary colour (ink in light, white in dark) so their
    /// labels stay readable; the cyan accent is for marks, links and icons.
    static let control = Color.primary
    static let onControl = Color(uiColor: .systemBackground)
    static let groupedBackground = Color(uiColor: .systemGroupedBackground)
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
    static let cardSecondary = Color(uiColor: .tertiarySystemGroupedBackground)
}

/// The small round badge beside a conversation. A working badge breathes.
struct FamiliarBadge: View {
    let working: Bool
    let label: String
    @State private var isBreathing = false

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    AngularGradient(
                        colors: [
                            BoltrigTheme.accent,
                            Color(red: 0.40, green: 0.72, blue: 0.97),
                            Color(red: 0.58, green: 0.38, blue: 0.90),
                            BoltrigTheme.accent,
                        ],
                        center: .center
                    )
                )
                .overlay {
                    Circle().stroke(.white.opacity(0.42), lineWidth: 1)
                }
                .shadow(color: BoltrigTheme.accent.opacity(working ? 0.35 : 0.14), radius: working ? 10 : 5)
                .scaleEffect(isBreathing && working ? 1.05 : 1)

            Circle()
                .fill(.white.opacity(0.20))
                .frame(width: 11, height: 11)
                .offset(x: -7, y: -8)
        }
        .frame(width: 42, height: 42)
        .accessibilityLabel(label)
        .onAppear {
            guard working else { return }
            withAnimation(.easeInOut(duration: 2.1).repeatForever(autoreverses: true)) {
                isBreathing = true
            }
        }
    }
}

struct StatusDot: View {
    let color: Color

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 9, height: 9)
    }
}

struct NoticeBanner: View {
    let message: String
    var symbol: String = "info.circle.fill"

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol)
                .foregroundStyle(BoltrigTheme.accent)
            Text(message)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BoltrigTheme.accent.opacity(0.09), in: RoundedRectangle(cornerRadius: 14))
    }
}
