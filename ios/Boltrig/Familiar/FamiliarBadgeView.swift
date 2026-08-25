import SwiftUI

/// The lightweight Familiar for lists and avatars: a port of the web's SVG badge
/// (apps/worker/src/components/familiar/FamiliarBadge.tsx) drawn in its 24-unit space.
/// A working badge breathes, as the web one does, unless Reduce Motion is on.
struct FamiliarBadgeView: View {
    var working: Bool
    var identity: FamiliarVisualIdentity = .neutral
    var size: CGFloat = 42
    var label: String = "Familiar"

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var breathing = false

    private var light: Color { Color(hex: identity.palette[0]) }
    private var mid: Color { Color(hex: identity.palette[1]) }
    private var dark: Color { Color(hex: identity.palette[2]) }

    var body: some View {
        Canvas { context, canvasSize in
            let scale = min(canvasSize.width, canvasSize.height) / 24
            context.scaleBy(x: scale, y: scale)
            drawRing(&context)
            drawBody(&context)
            drawMarkings(&context)
            drawAccessories(&context)
        }
        .frame(width: size, height: size)
        .scaleEffect(breathing && working && !reduceMotion ? 1.06 : 1)
        .accessibilityLabel(label)
        .accessibilityValue(working ? "working" : "ready")
        .onAppear {
            guard working, !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 1.55).repeatForever(autoreverses: true)) {
                breathing = true
            }
        }
    }

    // MARK: Ring and body

    private func drawRing(_ context: inout GraphicsContext) {
        let ring = Path(ellipseIn: CGRect(x: 12 - 10.35, y: 12 - 10.35, width: 20.7, height: 20.7))
        context.stroke(ring, with: .color((working ? light : dark).opacity(working ? 0.9 : 0.46)), lineWidth: 1.25)
    }

    private func drawBody(_ context: inout GraphicsContext) {
        var body = context
        if identity.bodyRotationDegrees != 0 {
            body.translateBy(x: 12, y: 12)
            body.rotate(by: .degrees(identity.bodyRotationDegrees))
            body.translateBy(x: -12, y: -12)
        }
        switch identity.body {
        case .cassini:
            var left = Path()
            left.move(to: CGPoint(x: 11.45, y: 4.1))
            left.addCurve(to: CGPoint(x: 5.7, y: 12), control1: CGPoint(x: 8.15, y: 4.1), control2: CGPoint(x: 5.7, y: 7.55))
            left.addCurve(to: CGPoint(x: 11.45, y: 19.9), control1: CGPoint(x: 5.7, y: 16.45), control2: CGPoint(x: 8.15, y: 19.9))
            left.closeSubpath()
            body.fill(left, with: .color(mid))
            var right = Path()
            right.move(to: CGPoint(x: 12.55, y: 4.1))
            right.addCurve(to: CGPoint(x: 18.3, y: 12), control1: CGPoint(x: 15.85, y: 4.1), control2: CGPoint(x: 18.3, y: 7.55))
            right.addCurve(to: CGPoint(x: 12.55, y: 19.9), control1: CGPoint(x: 18.3, y: 16.45), control2: CGPoint(x: 15.85, y: 19.9))
            right.closeSubpath()
            body.fill(right, with: .color(light.opacity(0.82)))
        case .kepler:
            let star = Self.radialPolygon(points: 5, outer: 8.1, inner: 3.45)
            body.fill(star, with: .color(mid))
            body.stroke(star, with: .color(dark), lineWidth: 0.35)
        case .pioneer:
            let star = Self.radialPolygon(points: 8, outer: 8.15, inner: 5.5)
            body.fill(star, with: .color(mid))
            body.stroke(star, with: .color(light), lineWidth: 0.4)
        case .voyager:
            var shield = Path()
            shield.move(to: CGPoint(x: 12, y: 3.65))
            shield.addLine(to: CGPoint(x: 18.45, y: 6))
            shield.addLine(to: CGPoint(x: 18.45, y: 11.3))
            shield.addCurve(to: CGPoint(x: 12, y: 19), control1: CGPoint(x: 18.45, y: 15.48), control2: CGPoint(x: 15.55, y: 17.92))
            shield.addCurve(to: CGPoint(x: 5.55, y: 11.3), control1: CGPoint(x: 8.45, y: 17.92), control2: CGPoint(x: 5.55, y: 15.48))
            shield.addLine(to: CGPoint(x: 5.55, y: 6))
            shield.closeSubpath()
            body.fill(shield, with: .color(mid))
            body.stroke(shield, with: .color(light), lineWidth: 0.45)
        case .neutral:
            body.fill(Path(ellipseIn: CGRect(x: 4.5, y: 4.5, width: 15, height: 15)), with: .color(mid))
        }
    }

    // MARK: Markings and accessories

    private func drawMarkings(_ context: inout GraphicsContext) {
        for marking in identity.markings {
            switch marking {
            case .arc:
                var arc = Path()
                arc.move(to: CGPoint(x: 7.2, y: 13.8))
                arc.addCurve(to: CGPoint(x: 16.55, y: 13.45), control1: CGPoint(x: 9.0, y: 15.95), control2: CGPoint(x: 13.35, y: 16.25))
                context.stroke(arc, with: .color(light), style: StrokeStyle(lineWidth: 1, lineCap: .round))
            case .constellation:
                var line = Path()
                line.move(to: CGPoint(x: 8.2, y: 14.9))
                line.addLine(to: CGPoint(x: 11.2, y: 9.7))
                line.addLine(to: CGPoint(x: 15.45, y: 12.8))
                context.stroke(line, with: .color(dark.opacity(0.8)), lineWidth: 0.35)
                for (centre, radius) in [(CGPoint(x: 8.2, y: 14.9), 0.8), (CGPoint(x: 11.2, y: 9.7), 0.7), (CGPoint(x: 15.45, y: 12.8), 0.85)] {
                    let dot = Path(ellipseIn: CGRect(x: centre.x - radius, y: centre.y - radius, width: radius * 2, height: radius * 2))
                    context.fill(dot, with: .color(light))
                    context.stroke(dot, with: .color(dark), lineWidth: 0.35)
                }
            case .halo:
                let halo = Path(ellipseIn: CGRect(x: 12 - 8.45, y: 12 - 8.45, width: 16.9, height: 16.9))
                context.stroke(halo, with: .color(light.opacity(0.78)), lineWidth: 0.9)
            case .orbit:
                var orbit = context
                orbit.translateBy(x: 12, y: 12)
                orbit.rotate(by: .degrees(-18))
                orbit.translateBy(x: -12, y: -12)
                let ellipse = Path(ellipseIn: CGRect(x: 12 - 8.7, y: 12 - 3.65, width: 17.4, height: 7.3))
                orbit.stroke(ellipse, with: .color(light.opacity(0.86)), lineWidth: 0.9)
            }
        }
    }

    private func drawAccessories(_ context: inout GraphicsContext) {
        for accessory in identity.accessories {
            switch accessory {
            case .antenna:
                var stalk = Path()
                stalk.move(to: CGPoint(x: 12, y: 4.35))
                stalk.addLine(to: CGPoint(x: 14.35, y: 2.3))
                context.stroke(stalk, with: .color(light), style: StrokeStyle(lineWidth: 0.9, lineCap: .round))
                let tip = Path(ellipseIn: CGRect(x: 14.65 - 0.9, y: 2.05 - 0.9, width: 1.8, height: 1.8))
                context.fill(tip, with: .color(mid))
                context.stroke(tip, with: .color(dark), lineWidth: 0.35)
            case .orbitRing:
                var ring = context
                ring.translateBy(x: 12, y: 12)
                ring.rotate(by: .degrees(24))
                ring.translateBy(x: -12, y: -12)
                let ellipse = Path(ellipseIn: CGRect(x: 12 - 10.1, y: 12 - 4.3, width: 20.2, height: 8.6))
                ring.stroke(ellipse, with: .color(light), lineWidth: 0.75)
            case .signalPin:
                var pin = Path()
                pin.move(to: CGPoint(x: 17.1, y: 5.7))
                pin.addCurve(to: CGPoint(x: 19.25, y: 3.5), control1: CGPoint(x: 17.1, y: 4.45), control2: CGPoint(x: 18.05, y: 3.5))
                pin.addCurve(to: CGPoint(x: 21.4, y: 5.7), control1: CGPoint(x: 20.45, y: 3.5), control2: CGPoint(x: 21.4, y: 4.45))
                pin.addCurve(to: CGPoint(x: 19.25, y: 9.25), control1: CGPoint(x: 21.4, y: 7.25), control2: CGPoint(x: 19.25, y: 9.25))
                pin.addCurve(to: CGPoint(x: 17.1, y: 5.7), control1: CGPoint(x: 19.25, y: 9.25), control2: CGPoint(x: 17.1, y: 7.25))
                pin.closeSubpath()
                context.fill(pin, with: .color(light))
                context.stroke(pin, with: .color(dark), lineWidth: 0.35)
                let core = Path(ellipseIn: CGRect(x: 19.25 - 0.65, y: 5.65 - 0.65, width: 1.3, height: 1.3))
                context.fill(core, with: .color(mid))
            }
        }
    }

    /// The web's `radialPoints`: alternating outer and inner radii around (12, 12), starting at the top.
    static func radialPolygon(points: Int, outer: Double, inner: Double) -> Path {
        var path = Path()
        for index in 0..<(points * 2) {
            let radius = index % 2 == 0 ? outer : inner
            let angle = Double.pi * Double(index) / Double(points)
            let point = CGPoint(x: 12 + radius * sin(angle), y: 12 - radius * cos(angle))
            if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
        }
        path.closeSubpath()
        return path
    }
}

extension Color {
    /// `#rrggbb` to Color; anything else is clear so a bad palette fails visibly, not silently.
    init(hex: String) {
        var value: UInt64 = 0
        let body = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        guard body.count == 6, Scanner(string: body).scanHexInt64(&value) else {
            self = .clear
            return
        }
        self.init(red: Double((value >> 16) & 0xFF) / 255,
                  green: Double((value >> 8) & 0xFF) / 255,
                  blue: Double(value & 0xFF) / 255)
    }
}
