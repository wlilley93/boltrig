import SwiftUI

/// The Boltrig mark: three open rings on ink with the cyan core, drawn from the same
/// geometry as assets/brand/boltrig-app-icon.svg so the sign-in screen and the icon agree.
struct BrandMark: View {
    var size: CGFloat = 96
    var onInk = true

    private static let ringFraction: CGFloat = 0.83
    private static let ink = Color(red: 0.016, green: 0.024, blue: 0.051)
    private static let ring = Color(red: 0.949, green: 0.969, blue: 0.988)
    private static let core = Color(red: 0.239, green: 0.827, blue: 0.941)

    var body: some View {
        ZStack {
            if onInk {
                RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                    .fill(Self.ink)
            }
            ring(radius: 0.45, rotation: 0)
            ring(radius: 0.31, rotation: -90)
            ring(radius: 0.17, rotation: 90)
            Circle()
                .fill(Self.core)
                .frame(width: size * 0.12 * 0.6, height: size * 0.12 * 0.6)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private func ring(radius: CGFloat, rotation: Double) -> some View {
        let diameter = size * 0.6 * radius * 2
        return Circle()
            .trim(from: 0, to: Self.ringFraction)
            .stroke(onInk ? Self.ring : Color.primary, style: StrokeStyle(lineWidth: size * 0.6 * 0.036, lineCap: .round))
            .frame(width: diameter, height: diameter)
            .rotationEffect(.degrees(rotation))
    }
}

#Preview {
    HStack(spacing: 24) {
        BrandMark(size: 120)
        BrandMark(size: 64, onInk: false)
    }
    .padding()
}
