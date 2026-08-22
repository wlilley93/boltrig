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
